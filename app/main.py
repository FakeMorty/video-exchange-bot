from app.models import LotteryTicket, User
import os
from sqlalchemy import func
from app.models import Video
from sqlalchemy import select
from alembic import command
from alembic.config import Config
import asyncio
from datetime import datetime, timezone, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from app.config import (
    BOT_TOKEN, PORT,
    OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS,
    OFFER_SUBSCRIPTION_CHECK_BATCH,
    ENABLE_SUBSCRIPTION_AUDIT,
    ENABLE_LOTTERY,
    LOTTERY_DRAW_SECRET,
    ADMINS,
)
from app.db import engine, init_db, async_session
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.user_offer_handlers import router as user_offer_router
from app.donation_shop import router as donation_router
from app.ai_assistant import router as ai_router
from app.logger import setup_logging, get_logger, log_info, log_error
from app.services import (
    get_offer_participations_for_subscription_audit,
    get_offer_by_id,
    get_user_by_id,
    apply_offer_unsubscribe_penalty,
    ensure_current_lottery_round,
    get_latest_lottery_round,
    get_lottery_state_dict,
    draw_next_lottery_number,
    settle_lottery_round,
)

setup_logging()
logger = get_logger(__name__)


def _chat_id_from_offer_url(channel_url: str) -> str | None:
    if not channel_url:
        return None
    url = channel_url.strip()
    if "t.me/" in url:
        url = url.split("t.me/", 1)[1]
    if url.startswith("@"):
        return url
    url = url.strip("/").split("?")[0]
    if not url:
        return None
    return f"@{url}"


async def _is_subscribed(bot: Bot, telegram_user_id: int, channel_url: str) -> bool:
    chat_id = _chat_id_from_offer_url(channel_url)
    if not chat_id:
        return False
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=telegram_user_id)
        return member.status in {"member", "administrator", "creator"}
    except TelegramBadRequest:
        return False
    except Exception:
        return False


async def subscription_audit_worker(bot: Bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        checked_count = 0
        penalized_count = 0
        penalized_total = 0
        try:
            async with async_session() as session:
                parts = await get_offer_participations_for_subscription_audit(
                    session,
                    limit=max(1, OFFER_SUBSCRIPTION_CHECK_BATCH),
                )

                for part in parts:
                    checked_count += 1
                    offer = await get_offer_by_id(session, part.offer_id)
                    user = await get_user_by_id(session, part.user_id)
                    if not offer or not user:
                        continue

                    subscribed = await _is_subscribed(bot, user.telegram_id, offer.channel_url)
                    if subscribed:
                        continue

                    rewarded_total, extra_penalty, total_charge = await apply_offer_unsubscribe_penalty(
                        session, user, offer, part
                    )
                    if total_charge <= 0:
                        continue
                    penalized_count += 1
                    penalized_total += float(total_charge)
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            (
                                "⚠️ Вы отписались от оффера после получения награды.\n\n"
                                f"Списано бонусов: {rewarded_total} монет\n"
                                f"Доп. штраф: {extra_penalty} монет\n"
                                f"Итого списано: {total_charge} монет"
                            ),
                        )
                    except Exception:
                        pass
            if checked_count:
                log_info(
                    logger,
                    (
                        "Subscription audit stats: "
                        f"checked={checked_count}, penalized={penalized_count}, "
                        f"total_charged={penalized_total:.2f}"
                    ),
                )
        except Exception as e:
            log_info(logger, f"Subscription audit warning: {e}")

        await asyncio.sleep(max(30, OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS))





async def notify_lottery_reminder(bot: Bot, session, round_id: int, draw_starts_at: datetime):
    """Напоминает владельцам билетов за 1 час до розыгрыша."""
    tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.round_id == round_id))).scalars().all()
    user_ids = list(set(t.user_id for t in tickets))
    users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    
    # Время в МСК для удобства
    draw_msk = draw_starts_at + timedelta(hours=3)
    time_str = draw_msk.strftime("%H:%M")
    
    msg = (
        f"⏰ <b>Лотерея-лото — скоро розыгрыш!</b>\n\n"
        f"Розыгрыш начнётся через час ({time_str} МСК).\n"
        f"Не забудьте зайти в Live и посмотреть на колесо удачи! 🎰"
    )
    for u in users:
        try:
            await bot.send_message(u.telegram_id, msg)
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def notify_lottery_started(bot: Bot, session, round_id: int):
    tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.round_id == round_id))).scalars().all()
    user_ids = list(set(t.user_id for t in tickets))
    users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    
    msg = f"🎰 <b>Лотерея #{round_id} началась!</b>\n\nЗаходите в Live, чтобы следить за розыгрышем в прямом эфире."
    for u in users:
        try:
            await bot.send_message(u.telegram_id, msg)
        except Exception:
            pass
        await asyncio.sleep(0.05)

async def notify_lottery_results(bot: Bot, session, round_id: int):
    tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.round_id == round_id))).scalars().all()
    user_ids = list(set(t.user_id for t in tickets))
    users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()}
    
    user_results = {}
    for t in tickets:
        if t.user_id not in user_results:
            user_results[t.user_id] = {"won": False, "matched": 0}
        user_results[t.user_id]["matched"] = max(user_results[t.user_id]["matched"], t.matched_count)
        if t.reward_paid:
            user_results[t.user_id]["won"] = True

    for uid, data in user_results.items():
        u = users.get(uid)
        if not u:
            continue
        if data["won"]:
            msg = f"🎉 <b>Поздравляем!</b> Ваш билет в лотерее #{round_id} оказался выигрышным!\nНаграда зачислена на ваш баланс."
        else:
            msg = f"😔 Лотерея #{round_id} завершена. К сожалению, ваш билет не выиграл.\nНе расстраивайтесь, повезет в следующий раз!"
        try:
            await bot.send_message(u.telegram_id, msg)
        except Exception:
            pass
        await asyncio.sleep(0.05)

async def lottery_worker(bot: Bot, stop_event: asyncio.Event):
    REMINDER_HOURS_BEFORE = 1  # За сколько часов до розыгрыша напомнить
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                round_obj = await ensure_current_lottery_round(session)
                utc_now = datetime.now(timezone.utc)

                # Напоминание за 1 час до розыгрыша
                if (
                    round_obj.status == "open"
                    and not round_obj.draw_reminder_sent
                    and utc_now >= round_obj.draw_starts_at - timedelta(hours=REMINDER_HOURS_BEFORE)
                ):
                    round_obj.draw_reminder_sent = True
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id}: sending draw reminder")
                    await notify_lottery_reminder(bot, session, round_obj.id, round_obj.draw_starts_at)

                if round_obj.status == "open" and utc_now >= round_obj.draw_starts_at:
                    round_obj.status = "drawing"
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id} moved to drawing")
                    await notify_lottery_started(bot, session, round_obj.id)

                if round_obj.status == "drawing" and utc_now >= round_obj.draw_ends_at:
                    while round_obj.status == "drawing":
                        next_num = await draw_next_lottery_number(session, round_obj)
                        if next_num is None:
                            break
                    stats = await settle_lottery_round(session, round_obj)
                    log_info(
                        logger,
                        f"Lottery round #{round_obj.id} settled: {stats}",
                    )
                    await notify_lottery_results(bot, session, round_obj.id)
        except Exception as e:
            log_info(logger, f"Lottery worker warning: {e}")

        await asyncio.sleep(30)


async def lottery_state_handler(request: web.Request) -> web.Response:
    async with async_session() as session:
        round_obj = await get_latest_lottery_round(session)
        return web.json_response(get_lottery_state_dict(round_obj))


async def lottery_draw_next_handler(request: web.Request) -> web.Response:
    secret = request.query.get("secret", "")
    if not LOTTERY_DRAW_SECRET or secret != LOTTERY_DRAW_SECRET:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    async with async_session() as session:
        round_obj = await get_latest_lottery_round(session)
        if not round_obj:
            return web.json_response({"ok": False, "error": "no_round"}, status=404)
        if round_obj.status not in {"drawing", "open"}:
            return web.json_response({"ok": False, "error": "round_not_drawing"}, status=400)
        if round_obj.status == "open":
            round_obj.status = "drawing"
            await session.commit()
        num = await draw_next_lottery_number(session, round_obj)
        if num is None:
            stats = await settle_lottery_round(session, round_obj)
            return web.json_response({"ok": True, "finished": True, "stats": stats})
        if round_obj.status == "completed":
            stats = await settle_lottery_round(session, round_obj)
            return web.json_response(
                {"ok": True, "number": num, "finished": True, "stats": stats, "state": get_lottery_state_dict(round_obj)}
            )
        return web.json_response({"ok": True, "number": num, "state": get_lottery_state_dict(round_obj)})


async def lottery_live_page_handler(request: web.Request) -> web.Response:
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Lottery Live</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body {
      margin: 0;
      padding: 20px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--tg-theme-bg-color, #ffffff);
      color: var(--tg-theme-text-color, #000000);
    }
    .header { text-align: center; margin-bottom: 20px; }
    .status-badge {
      display: inline-block;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 14px;
      font-weight: bold;
      background-color: var(--tg-theme-hint-color, #999);
      color: var(--tg-theme-button-text-color, #fff);
    }
    .status-open { background-color: #34c759; }
    .status-drawing { background-color: #ff9500; animation: pulse 1s infinite alternate; }
    .status-completed { background-color: #007aff; }
    @keyframes pulse {
      from { opacity: 1; }
      to { opacity: 0.6; }
    }
    .prize-pool {
      font-size: 28px;
      font-weight: 800;
      margin: 15px 0;
      color: var(--tg-theme-button-color, #3390ec);
    }
    .balls-container {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: center;
      margin-top: 30px;
      min-height: 60px;
    }
    .ball {
      width: 50px;
      height: 50px;
      border-radius: 50%;
      background: radial-gradient(circle at 30% 30%, #ffd700, #ff9500);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      font-weight: bold;
      box-shadow: 0 4px 10px rgba(0,0,0,0.2);
      animation: popIn 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
    }
    @keyframes popIn {
      from { transform: scale(0); opacity: 0; }
      to { transform: scale(1); opacity: 1; }
    }
    .card {
      background-color: var(--tg-theme-secondary-bg-color, #f0f0f0);
      border-radius: 15px;
      padding: 20px;
      text-align: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .info-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      font-size: 15px;
      border-bottom: 1px solid var(--tg-theme-hint-color, #ccc);
      padding-bottom: 5px;
    }
    .info-row:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h2>🏆 Лотерея <span id="round-id">...</span></h2>
      <div id="status-badge" class="status-badge">Загрузка...</div>
    </div>
    <div style="text-align: center; margin: 20px 0;">
      <div style="font-size: 14px; color: var(--tg-theme-hint-color);">Призовой фонд</div>
      <div class="prize-pool" id="prize-pool">0.00 🪙</div>
    </div>
    <div class="info-row">
      <span style="color: var(--tg-theme-hint-color);">Цена билета:</span>
      <strong id="ticket-price">-</strong>
    </div>
    <div class="info-row">
      <span style="color: var(--tg-theme-hint-color);">Куплено билетов:</span>
      <strong id="tickets-count">-</strong>
    </div>
    <div class="info-row">
      <span style="color: var(--tg-theme-hint-color);">Старт розыгрыша:</span>
      <strong id="draw-time">-</strong>
    </div>
  </div>

  <h3 style="text-align: center; margin-top: 30px;">Выпавшие числа</h3>
  <div class="balls-container" id="balls-container">
  </div>

  <script>
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();

    let lastRoundId = null;

    function updateUI(data) {
        document.getElementById('round-id').innerText = '#' + data.id;
        
        let statusText = '';
        let badgeClass = 'status-badge ';
        if (data.status === 'open') {
            statusText = 'Открыта';
            badgeClass += 'status-open';
        } else if (data.status === 'drawing') {
            statusText = 'Идет розыгрыш!';
            badgeClass += 'status-drawing';
        } else if (data.status === 'completed') {
            statusText = 'Завершена';
            badgeClass += 'status-completed';
        }
        
        const badge = document.getElementById('status-badge');
        badge.innerText = statusText;
        badge.className = badgeClass;

        document.getElementById('prize-pool').innerText = data.prize_pool + ' 🪙';
        document.getElementById('ticket-price').innerText = data.ticket_price + ' 🪙';
        document.getElementById('tickets-count').innerText = data.tickets_count;
        
        // Data contains ISO UTC string without Z if we don't append it, assuming the API returns valid string.
        let drawDateStr = data.draw_starts_at;
        if (!drawDateStr.endsWith('Z')) drawDateStr += 'Z';
        const drawDate = new Date(drawDateStr);
        document.getElementById('draw-time').innerText = drawDate.toLocaleString();

        const container = document.getElementById('balls-container');
        
        if (lastRoundId !== data.id) {
            container.innerHTML = '';
            lastRoundId = data.id;
        }

        if (data.drawn_numbers && data.drawn_numbers.length > 0) {
            const currentBalls = container.querySelectorAll('.ball').length;
            if (data.drawn_numbers.length > currentBalls) {
                // remove "no numbers" message if exists
                if (container.querySelector('.no-numbers')) {
                    container.innerHTML = '';
                }
                for (let i = currentBalls; i < data.drawn_numbers.length; i++) {
                    const ball = document.createElement('div');
                    ball.className = 'ball';
                    ball.innerText = data.drawn_numbers[i];
                    container.appendChild(ball);
                    if (window.Telegram.WebApp.HapticFeedback) {
                        window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
                    }
                }
            } else if (data.drawn_numbers.length < currentBalls) {
                container.innerHTML = ''; // should not happen unless round changed, but handled above
            }
        } else {
            if (container.children.length === 0) {
                container.innerHTML = '<div class="no-numbers" style="color: var(--tg-theme-hint-color); font-size: 14px; text-align:center; width:100%;">Пока нет чисел...</div>';
            }
        }
    }

    async function tick() {
      try {
        const res = await fetch('/lottery/state');
        if(res.ok) {
            const data = await res.json();
            updateUI(data);
        }
      } catch (e) {
        console.error('Fetch error:', e);
      }
    }
    
    setInterval(tick, 1000);
    tick();
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")




async def api_sextok_feed(request: web.Request) -> web.Response:
    try:
        async with async_session() as session:
            videos = (await session.execute(
                select(Video).where(Video.status == "approved")
                .order_by(func.random()).limit(10)
            )).scalars().all()
            
            data = [{"id": v.id, "author": v.uploader_user_id} for v in videos]
            headers = {"Access-Control-Allow-Origin": "*"}
            return web.json_response({"videos": data}, headers=headers)
    except Exception:
        return web.json_response({"error": "Internal Server Error"}, status=500)

async def api_video_stream(request: web.Request) -> web.Response:
    video_id = request.match_info.get("id")
    if not video_id or not video_id.isdigit():
        return web.Response(status=400, text="Invalid ID")

    async with async_session() as session:
        video = await session.get(Video, int(video_id))
        if not video:
            return web.Response(status=404, text="Not found")
        if video.status != "approved" or video.content_type != "video":
            return web.Response(status=403, text="Forbidden")

    bot = request.app['bot']
    cache_dir = "video_cache"
    os.makedirs(cache_dir, exist_ok=True)
    file_path_local = os.path.join(cache_dir, f"{video.telegram_file_unique_id}.mp4")

    if not os.path.exists(file_path_local):
        try:
            tg_file = await bot.get_file(video.telegram_file_id)
            await bot.download_file(tg_file.file_path, file_path_local)
        except TelegramBadRequest as e:
            # File might be larger than 20MB
            return web.Response(status=400, text=f"TG API Error: {str(e)}. File might be >20MB.")
        except Exception as e:
            return web.Response(status=500, text=str(e))

    response = web.FileResponse(file_path_local)
    response.content_type = 'video/mp4'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def sextok_page_handler(request: web.Request) -> web.Response:
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>SexTok</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #000; overflow: hidden; font-family: -apple-system, sans-serif;}
    .feed {
      width: 100%; height: 100%; overflow-y: scroll; scroll-snap-type: y mandatory; scroll-behavior: smooth;
    }
    .video-container {
      width: 100%; height: 100%; scroll-snap-align: start; position: relative;
      display: flex; justify-content: center; align-items: center; background: #111;
    }
    video {
      width: 100%; height: 100%; object-fit: cover; cursor: pointer;
    }
    .overlay {
      position: absolute; bottom: 80px; right: 15px; display: flex; flex-direction: column; gap: 20px; z-index: 10;
    }
    .btn {
      width: 45px; height: 45px; background: rgba(255,255,255,0.2); border-radius: 50%;
      display: flex; justify-content: center; align-items: center; color: white; font-size: 20px;
      backdrop-filter: blur(5px); cursor: pointer;
    }
    .loading {
      position: absolute; color: rgba(255,255,255,0.5); font-size: 16px; z-index: 1; pointer-events: none;
    }
    .mute-btn {
      position: absolute; top: 20px; right: 20px; width: 40px; height: 40px; background: rgba(0,0,0,0.5); 
      color: white; border-radius: 50%; display: flex; justify-content: center; align-items: center; z-index: 10;
      cursor: pointer; backdrop-filter: blur(5px);
    }
  </style>
</head>
<body>
  <div class="feed" id="feed">
     <div style="color:white; text-align:center; padding-top: 50vh;">Загрузка ленты...</div>
  </div>
  <script>
     window.Telegram.WebApp.ready();
     window.Telegram.WebApp.expand();
     
     let isMuted = true;

     async function loadFeed() {
        try {
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Fetching API...</div>';
            
            let host = window.location.origin;
            if (host === "null" || host === "about:blank" || !host.startsWith("http")) {
                host = window.location.href.split('/').slice(0, 3).join('/');
            }
            const api_url = host + '/api/sextok/feed';
            
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Fetching: ' + api_url + '</div>';
            
            const res = await fetch(api_url);
            
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Reading Response...</div>';
            const textRaw = await res.text();
            let data;
            try {
                data = JSON.parse(textRaw);
            } catch(e) {
                document.getElementById('feed').innerHTML = '<div style="color:red; padding: 20px;">Parse error: ' + e.message + '<br><br>' + textRaw + '</div>';
                return;
            }
            
            if(data.error) {
                document.getElementById('feed').innerHTML = '<div style="color:red; padding: 20px;">Server error: ' + data.error + '</div>';
                return;
            }
            const feed = document.getElementById('feed');
            feed.innerHTML = ''; // clear loading
            
            if(data.videos.length === 0) {
                feed.innerHTML = '<div style="color:white; text-align:center; padding-top: 50vh;">Нет доступных видео.<br>Загрузите видео в бота!</div>';
                return;
            }

            data.videos.forEach(v => {
                const container = document.createElement('div');
                container.className = 'video-container';
                container.innerHTML = `
                    <div class="loading">Загрузка видео...</div>
                    <video src="/api/video/${v.id}" loop playsinline preload="auto" muted crossOrigin="anonymous" style="background:transparent;"></video>
                    <div class="mute-btn" onclick="toggleMute(event)">🔇</div>
                    <div class="overlay">
                        <div class="btn" onclick="window.Telegram.WebApp.HapticFeedback.impactOccurred('medium'); alert('Функция лайков в разработке!')">❤️</div>
                        <div class="btn" onclick="window.Telegram.WebApp.HapticFeedback.impactOccurred('medium'); alert('Донаты автору в разработке!')">💸</div>
                    </div>
                `;
                
                const vid = container.querySelector('video');
                vid.addEventListener('click', () => {
                    if(vid.paused) vid.play();
                    else vid.pause();
                });
                
                vid.addEventListener('loadeddata', () => {
                    const l = container.querySelector('.loading');
                    if(l) l.remove();
                });

                feed.appendChild(container);
            });
            setupObserver();
        } catch(e) {
            document.getElementById('feed').innerHTML = '<div style="color:red; text-align:center; padding-top: 50vh;">Ошибка загрузки видео.</div>';
        }
     }
     
     window.toggleMute = function(e) {
         if(e) e.stopPropagation();
         isMuted = !isMuted;
         document.querySelectorAll('video').forEach(v => v.muted = isMuted);
         document.querySelectorAll('.mute-btn').forEach(btn => btn.innerText = isMuted ? '🔇' : '🔊');
     };

     function setupObserver() {
        const videos = document.querySelectorAll('video');
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if(entry.isIntersecting) {
                    entry.target.muted = isMuted;
                    let playPromise = entry.target.play();
                    if (playPromise !== undefined) {
                        playPromise.catch(error => {
                            console.log('Autoplay prevented:', error);
                        });
                    }
                } else {
                    entry.target.pause();
                    entry.target.currentTime = 0;
                }
            });
        }, { threshold: 0.6 });
        videos.forEach(v => observer.observe(v));
     }
     loadFeed();
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")

async def handle_health_check(request):
    """Handler for Render health checks"""
    return web.Response(text="Bot is running", status=200)

async def _notify_admins_started(bot: Bot) -> None:
    text = '✅ Бот запущен и готов к работе!'
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


async def _mod_notification_loop(bot):
    """Периодическая отправка агрегированных уведомлений о модерации."""
    await asyncio.sleep(60)  # подождать старта
    while True:
        try:
            await asyncio.sleep(120)  # каждые 2 минуты
            from app.db import async_session
            from app.services import should_flush_notifications, flush_mod_notifications
            async with async_session() as session:
                if await should_flush_notifications(session):
                    await flush_mod_notifications(bot, session)
        except Exception as e:
            log_error(logger, f"Mod notification loop error: {e}")
            await asyncio.sleep(300)


async def video_cache_cleanup_worker(stop_event: asyncio.Event):
    """Периодически очищает кэш видео, если он стал слишком большим."""
    cache_dir = "video_cache"
    MAX_CACHE_SIZE_MB = 2000  # 2 ГБ
    CLEANUP_INTERVAL = 3600  # Раз в час
    while not stop_event.is_set():
        try:
            if os.path.exists(cache_dir):
                total_size = 0
                files = []
                for f in os.listdir(cache_dir):
                    path = os.path.join(cache_dir, f)
                    if os.path.isfile(path):
                        size = os.path.getsize(path)
                        total_size += size
                        files.append((path, os.path.getmtime(path), size))
                
                if total_size > MAX_CACHE_SIZE_MB * 1024 * 1024:
                    # Сортируем по времени модификации (старые в начале)
                    files.sort(key=lambda x: x[1])
                    while total_size > MAX_CACHE_SIZE_MB * 1024 * 1024 and files:
                        path, _, size = files.pop(0)
                        os.remove(path)
                        total_size -= size
                    log_info(logger, f"Video cache cleaned. Current size: {total_size / (1024*1024):.2f} MB")
        except Exception as e:
            log_error(logger, f"Video cache cleanup error: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL)


async def on_startup(app):
    bot = app['bot']
    await init_db()
    
    # DB Maintenance
    from app.utils.db_fix import fix_database
    try:
        await fix_database()
        log_info(logger, "Database maintenance complete")
    except Exception as e:
        log_error(logger, f"Database maintenance error: {e}")

    try:
        def run_migrations():
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")
        
        await asyncio.to_thread(run_migrations)
        log_info(logger, "Alembic migrations synced")
    except Exception as e:
        log_error(logger, f"Migration sync error: {e}")
        
    await _notify_admins_started(bot)

    # Загрузка стикеров Кати
    try:
        from app.ai_assistant import load_sticker_set
        await load_sticker_set(bot)
    except Exception as e:
        log_error(logger, f"Katya sticker load error: {e}")

    # Фоновая задача: агрегированные уведомления модерации
    asyncio.create_task(_mod_notification_loop(bot))
    log_info(logger, "Service initialized")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    from app.middlewares import BanCheckMiddleware
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(user_offer_router)
    dp.include_router(donation_router)
    dp.include_router(ai_router)

    app = web.Application()
    app['bot'] = bot
    app.on_startup.append(on_startup)
    app.router.add_get("/", handle_health_check)
    app.router.add_get("/sextok", sextok_page_handler)
    app.router.add_get("/api/sextok/feed", api_sextok_feed)
    app.router.add_get("/api/video/{id}", api_video_stream)
    app.router.add_get("/lottery/state", lottery_state_handler)
    app.router.add_post("/lottery/draw-next", lottery_draw_next_handler)
    app.router.add_get("/lottery/live", lottery_live_page_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(PORT or 10000))
    await site.start()

    try:
        log_info(logger, "Polling started")
        stop_event = asyncio.Event()
        audit_task = None
        lottery_task = None
        if ENABLE_SUBSCRIPTION_AUDIT:
            audit_task = asyncio.create_task(subscription_audit_worker(bot, stop_event))
            log_info(logger, "Subscription audit worker enabled")
        else:
            log_info(logger, "Subscription audit worker disabled by config")
        if ENABLE_LOTTERY:
            lottery_task = asyncio.create_task(lottery_worker(bot, stop_event))
            log_info(logger, "Lottery worker enabled")
        
        cache_task = asyncio.create_task(video_cache_cleanup_worker(stop_event))
        log_info(logger, "Video cache cleanup worker enabled")
        
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        if audit_task is not None:
            audit_task.cancel()
            try:
                await audit_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if lottery_task is not None:
            lottery_task.cancel()
            try:
                await lottery_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if cache_task is not None:
            cache_task.cancel()
            try:
                await cache_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

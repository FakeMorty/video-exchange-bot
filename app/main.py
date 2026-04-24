import asyncio
from datetime import datetime
import os
import subprocess
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
from app.logger import setup_logging, get_logger, log_info
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

def _git_meta() -> tuple[str, str] | tuple[None, None]:
    """
    Returns (version_str, subject) best-effort.
    version_str: commit count or short hash
    subject: last commit subject
    """
    # Prefer Render env vars if present
    render_commit = (os.getenv("RENDER_GIT_COMMIT") or "").strip()
    if render_commit:
        short_hash = render_commit[:7]
        return short_hash, "deploy"

    try:
        # commit count
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        subject = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        return count, subject
    except Exception:
        try:
            short_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=2,
                text=True,
            ).strip()
            subject = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%s"],
                stderr=subprocess.DEVNULL,
                timeout=2,
                text=True,
            ).strip()
            return short_hash, subject
        except Exception:
            return None, None


async def _notify_admins_started(bot: Bot) -> None:
    version, subject = _git_meta()
    if not version:
        return
    subj = (subject or "").strip()
    if len(subj) > 120:
        subj = subj[:120] + "…"
    text = f'✅ Бот работает на версии <b>{version}</b>\n<code>{subj}</code>'
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


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


async def lottery_worker(bot: Bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                round_obj = await ensure_current_lottery_round(session)
                utc_now = datetime.utcnow()

                if round_obj.status == "open" and utc_now >= round_obj.draw_starts_at:
                    round_obj.status = "drawing"
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id} moved to drawing")

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
    html = r"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Лотерея — Live</title>
  <style>
    :root{
      --bg0:#070A14;
      --bg1:#0C1024;
      --card:rgba(255,255,255,.06);
      --stroke:rgba(255,255,255,.10);
      --text:#EAF0FF;
      --muted:rgba(234,240,255,.70);
      --good:#6DFFA8;
      --bad:#FF6D8B;
      --accent:#8C7CFF;
      --accent2:#00D4FF;
      --shadow: 0 22px 80px rgba(0,0,0,.55);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Apple Color Emoji","Segoe UI Emoji";
      color:var(--text);
      background:
        radial-gradient(1100px 700px at 20% 0%, rgba(140,124,255,.22), transparent 55%),
        radial-gradient(900px 600px at 90% 10%, rgba(0,212,255,.16), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      min-height:100vh;
    }
    .wrap{max-width:1150px;margin:0 auto;padding:28px 18px 36px}
    header{
      display:flex;align-items:flex-start;justify-content:space-between;gap:18px;
      margin-bottom:18px;
    }
    .brand{
      display:flex;flex-direction:column;gap:6px;
    }
    .brand h1{
      margin:0;
      font-size:22px;
      letter-spacing:.2px;
      font-weight:760;
    }
    .brand .sub{
      color:var(--muted);
      font-size:13px;
      line-height:1.35;
    }
    .pillrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:flex-end}
    .pill{
      border:1px solid var(--stroke);
      background:rgba(255,255,255,.05);
      padding:8px 10px;
      border-radius:12px;
      box-shadow:0 12px 45px rgba(0,0,0,.28);
      font-size:12.5px;
      color:var(--muted);
    }
    .pill b{color:var(--text);font-weight:750}
    .grid{
      display:grid;
      grid-template-columns: 1.25fr .95fr;
      gap:14px;
      align-items:stretch;
    }
    @media (max-width: 980px){ .grid{grid-template-columns:1fr} }
    .card{
      border:1px solid var(--stroke);
      background:var(--card);
      border-radius:18px;
      box-shadow:var(--shadow);
      padding:14px;
      overflow:hidden;
      position:relative;
    }
    .wheelCard{
      display:grid;
      grid-template-columns: 470px 1fr;
      gap:14px;
      align-items:center;
      min-height:520px;
    }
    @media (max-width: 980px){
      .wheelCard{grid-template-columns:1fr;min-height:auto}
    }
    .wheelStage{
      position:relative;
      width:470px;
      height:470px;
      margin:0 auto;
    }
    @media (max-width: 560px){
      .wheelStage{width:330px;height:330px}
    }
    canvas{display:block;width:100%;height:100%}
    .glow{
      position:absolute;inset:-40px;
      background:radial-gradient(circle at 50% 50%, rgba(140,124,255,.34), transparent 58%);
      filter: blur(10px);
      opacity:.9; pointer-events:none;
    }
    .pointer{
      position:absolute;
      left:50%;
      top:-10px;
      transform:translateX(-50%);
      width:0;height:0;
      border-left:14px solid transparent;
      border-right:14px solid transparent;
      border-bottom:26px solid rgba(255,255,255,.88);
      filter: drop-shadow(0 10px 25px rgba(0,0,0,.55));
    }
    .hub{
      position:absolute;
      left:50%; top:50%;
      transform:translate(-50%,-50%);
      width:96px; height:96px;
      border-radius:999px;
      background: linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,.08));
      border:1px solid rgba(255,255,255,.22);
      box-shadow: 0 20px 70px rgba(0,0,0,.55);
      display:flex;align-items:center;justify-content:center;
      text-align:center;
      padding:10px;
    }
    .hub .big{font-size:20px;font-weight:900;line-height:1;color:var(--text)}
    .hub .small{font-size:11px;color:var(--muted);margin-top:4px}
    .rightCol{display:flex;flex-direction:column;gap:12px}
    .statgrid{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:10px;
    }
    .stat{
      border:1px solid var(--stroke);
      background:rgba(0,0,0,.16);
      border-radius:14px;
      padding:10px 12px;
    }
    .stat .k{font-size:12px;color:var(--muted)}
    .stat .v{margin-top:6px;font-size:16px;font-weight:800}
    .stat .v small{font-size:12px;color:var(--muted);font-weight:650}
    .callout{
      border:1px solid rgba(140,124,255,.35);
      background: linear-gradient(180deg, rgba(140,124,255,.14), rgba(140,124,255,.06));
      border-radius:14px;
      padding:10px 12px;
      color:var(--text);
    }
    .callout .t{font-weight:900}
    .callout .d{margin-top:6px;color:var(--muted);font-size:12.5px;line-height:1.35}
    .numsCard{padding:14px}
    .numsHead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
    .numsHead h3{margin:0;font-size:14px;color:var(--muted);font-weight:800;letter-spacing:.2px}
    .badge{
      font-size:12px;padding:6px 10px;border-radius:999px;
      border:1px solid var(--stroke);
      background:rgba(255,255,255,.05);
      color:var(--muted);
    }
    .nums{
      display:grid;
      grid-template-columns: repeat(9, 1fr);
      gap:8px;
    }
    @media (max-width: 980px){
      .nums{grid-template-columns: repeat(8, 1fr)}
    }
    @media (max-width: 560px){
      .nums{grid-template-columns: repeat(6, 1fr)}
    }
    .num{
      border-radius:12px;
      padding:8px 0;
      text-align:center;
      border:1px solid rgba(255,255,255,.10);
      background:rgba(255,255,255,.04);
      font-weight:850;
      font-size:13px;
      color:rgba(234,240,255,.92);
      user-select:none;
    }
    .num.drawn{
      background:rgba(109,255,168,.12);
      border-color:rgba(109,255,168,.35);
      color:var(--good);
      box-shadow: 0 14px 40px rgba(109,255,168,.08);
    }
    .num.last{
      background:rgba(0,212,255,.12);
      border-color:rgba(0,212,255,.35);
      color:rgba(180,250,255,.98);
      box-shadow: 0 16px 45px rgba(0,212,255,.10);
    }
    .footer{
      margin-top:14px;
      color:var(--muted);
      font-size:12px;
      display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;
    }
    .link{color:rgba(180,250,255,.95);text-decoration:none}
    .link:hover{text-decoration:underline}
    .toast{
      position:fixed;
      left:50%;
      bottom:18px;
      transform:translateX(-50%);
      background:rgba(0,0,0,.55);
      border:1px solid rgba(255,255,255,.12);
      color:var(--text);
      padding:10px 12px;
      border-radius:14px;
      box-shadow:0 22px 70px rgba(0,0,0,.6);
      display:none;
      max-width: min(640px, 92vw);
      backdrop-filter: blur(10px);
    }
    .toast.show{display:block;animation: pop .18s ease-out}
    @keyframes pop{from{transform:translateX(-50%) translateY(6px);opacity:.0}to{transform:translateX(-50%) translateY(0);opacity:1}}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="brand">
        <h1>🎰 Лотерея — Live</h1>
        <div class="sub">Колесо обновляется автоматически. Как только выпадает новое число — колесо красиво прокрутится и подсветит результат.</div>
      </div>
      <div class="pillrow">
        <div class="pill"><b id="pillStatus">…</b></div>
        <div class="pill">Раунд: <b id="pillRound">…</b></div>
        <div class="pill">Банк: <b id="pillPool">…</b> монет</div>
        <div class="pill">Цена билета: <b id="pillTicket">…</b></div>
      </div>
    </header>

    <div class="grid">
      <div class="card wheelCard">
        <div class="wheelStage">
          <div class="glow"></div>
          <div class="pointer"></div>
          <canvas id="wheel"></canvas>
          <canvas id="fx" style="position:absolute;inset:0;pointer-events:none;"></canvas>
          <div class="hub">
            <div>
              <div class="big" id="hubNum">—</div>
              <div class="small" id="hubHint">последнее число</div>
            </div>
          </div>
        </div>
        <div class="rightCol">
          <div class="statgrid">
            <div class="stat">
              <div class="k">До розыгрыша</div>
              <div class="v" id="countdown">…</div>
            </div>
            <div class="stat">
              <div class="k">Сколько уже выпало</div>
              <div class="v"><span id="drawnCount">0</span> <small>из</small> <span id="needCount">0</span></div>
            </div>
            <div class="stat">
              <div class="k">Диапазон чисел</div>
              <div class="v">1–<span id="poolN">…</span></div>
            </div>
            <div class="stat">
              <div class="k">Обновление</div>
              <div class="v"><span id="tickInfo">каждые 2с</span></div>
            </div>
          </div>
          <div class="callout">
            <div class="t">🗓 Розыгрыш по расписанию</div>
            <div class="d" id="scheduleLine">…</div>
          </div>
          <div class="callout">
            <div class="t">🔎 Прозрачность</div>
            <div class="d">Эта страница берёт данные из <code>/lottery/state</code>. Если ты видишь число здесь — оно есть в базе.</div>
          </div>
          <div class="footer">
            <div>Live: <a class="link" href="/lottery/live">/lottery/live</a></div>
            <div>API: <a class="link" href="/lottery/state">/lottery/state</a></div>
          </div>
        </div>
      </div>

      <div class="card numsCard">
        <div class="numsHead">
          <h3>Выпавшие числа</h3>
          <div class="badge" id="lastBadge">Последнее: —</div>
        </div>
        <div class="nums" id="nums"></div>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

<script>
  const wheel = document.getElementById('wheel');
  const fx = document.getElementById('fx');
  const ctx = wheel.getContext('2d');
  const fctx = fx.getContext('2d');
  let state = null;
  let lastLen = 0;
  let lastNumber = null;
  let spinAnim = null;

  function resizeCanvases(){
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const w = wheel.clientWidth;
    const h = wheel.clientHeight;
    wheel.width = Math.floor(w * dpr);
    wheel.height = Math.floor(h * dpr);
    fx.width = wheel.width;
    fx.height = wheel.height;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    fctx.setTransform(dpr,0,0,dpr,0,0);
    drawWheel();
    drawFx(0);
  }
  window.addEventListener('resize', resizeCanvases);

  function fmtMoney(x){
    if (typeof x !== 'number') return '—';
    return (Math.round(x * 100) / 100).toFixed(2).replace(/\.00$/, '');
  }
  function parseISO(s){
    try { return new Date(s); } catch { return null; }
  }
  function msToHuman(ms){
    ms = Math.max(0, ms|0);
    const s = Math.floor(ms/1000);
    const d = Math.floor(s/86400);
    const h = Math.floor((s%86400)/3600);
    const m = Math.floor((s%3600)/60);
    const ss = s%60;
    if (d>0) return `${d}д ${h}ч ${m}м`;
    if (h>0) return `${h}ч ${m}м`;
    if (m>0) return `${m}м ${ss}с`;
    return `${ss}с`;
  }
  function setText(id, v){ const el=document.getElementById(id); if(el) el.textContent = v; }
  function setHTML(id, v){ const el=document.getElementById(id); if(el) el.innerHTML = v; }

  function toast(msg){
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(()=>el.classList.remove('show'), 2800);
  }

  function colorForIdx(i){
    const a = 0.22;
    const b = 0.12;
    // alternating accent hues
    return i % 2 === 0
      ? `rgba(140,124,255,${a})`
      : `rgba(0,212,255,${b})`;
  }

  function drawWheel(rotation=0){
    if (!state) {
      ctx.clearRect(0,0,wheel.clientWidth,wheel.clientHeight);
      return;
    }
    const N = Math.max(10, state.numbers_pool || 36);
    const drawn = new Set(state.drawn_numbers || []);
    const w = wheel.clientWidth, h = wheel.clientHeight;
    const cx = w/2, cy = h/2;
    const R = Math.min(w,h)/2 - 6;
    const rInner = R * 0.18;
    ctx.clearRect(0,0,w,h);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rotation);

    const step = (Math.PI * 2) / N;
    for (let i=0;i<N;i++){
      const num = i+1;
      const a0 = -Math.PI/2 + i*step;
      const a1 = a0 + step;
      // slice
      ctx.beginPath();
      ctx.moveTo(0,0);
      ctx.arc(0,0,R,a0,a1,false);
      ctx.closePath();
      const isDrawn = drawn.has(num);
      const base = isDrawn ? 'rgba(109,255,168,.22)' : colorForIdx(i);
      const grad = ctx.createRadialGradient(0,0,rInner,0,0,R);
      grad.addColorStop(0, 'rgba(255,255,255,.08)');
      grad.addColorStop(1, base);
      ctx.fillStyle = grad;
      ctx.fill();

      // border
      ctx.strokeStyle = 'rgba(255,255,255,.10)';
      ctx.lineWidth = 1;
      ctx.stroke();

      // number
      const mid = (a0+a1)/2;
      ctx.save();
      ctx.rotate(mid);
      ctx.translate(0, -R*0.74);
      ctx.rotate(-mid);
      ctx.fillStyle = isDrawn ? 'rgba(234,240,255,.95)' : 'rgba(234,240,255,.82)';
      ctx.font = `800 ${Math.max(12, Math.floor(R*0.07))}px system-ui, Arial`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(num), 0, 0);
      ctx.restore();
    }

    // outer ring
    ctx.beginPath();
    ctx.arc(0,0,R,0,Math.PI*2);
    ctx.strokeStyle = 'rgba(255,255,255,.18)';
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.restore();
  }

  // Confetti FX (tiny)
  let confetti = [];
  function spawnConfetti(){
    const w = fx.clientWidth, h = fx.clientHeight;
    const colors = ['#8C7CFF','#00D4FF','#6DFFA8','#FFD36D','#FF6D8B','#EAF0FF'];
    for(let i=0;i<160;i++){
      confetti.push({
        x: w/2 + (Math.random()-0.5)*40,
        y: h*0.15 + (Math.random()-0.5)*20,
        vx: (Math.random()-0.5)*6,
        vy: 2 + Math.random()*6,
        r: 2 + Math.random()*3,
        a: Math.random()*Math.PI*2,
        va: (Math.random()-0.5)*0.3,
        c: colors[(Math.random()*colors.length)|0],
        life: 140 + (Math.random()*60)|0,
      });
    }
  }
  function drawFx(){
    const w = fx.clientWidth, h = fx.clientHeight;
    fctx.clearRect(0,0,w,h);
    confetti = confetti.filter(p=>p.life>0);
    for(const p of confetti){
      p.life -= 1;
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.06;
      p.a += p.va;
      fctx.save();
      fctx.translate(p.x,p.y);
      fctx.rotate(p.a);
      fctx.fillStyle = p.c;
      fctx.globalAlpha = Math.max(0, Math.min(1, p.life/160));
      fctx.fillRect(-p.r, -p.r, p.r*2.2, p.r*1.3);
      fctx.restore();
    }
    if(confetti.length){
      requestAnimationFrame(drawFx);
    }
  }

  function angleForNumber(n){
    const N = Math.max(10, state.numbers_pool || 36);
    const step = (Math.PI*2)/N;
    // center angle for this slice
    const mid = -Math.PI/2 + (n-1)*step + step/2;
    // pointer is at -pi/2 in world coords; we rotate wheel so that slice mid aligns with -pi/2
    return -mid;
  }

  function spinToNumber(n){
    if (!state) return;
    const target = angleForNumber(n);
    const extra = (Math.PI*2) * (4 + Math.floor(Math.random()*3)); // 4-6 full spins
    const from = spinAnim?.rot ?? 0;
    const to = target + extra;
    const dur = 2400 + Math.floor(Math.random()*600);
    const t0 = performance.now();

    const easeOut = (t) => 1 - Math.pow(1-t, 3);

    spinAnim = {rot: from};
    function step(now){
      const t = Math.min(1, (now - t0)/dur);
      const e = easeOut(t);
      const rot = from + (to-from)*e;
      spinAnim.rot = rot;
      drawWheel(rot);
      if(t < 1){
        requestAnimationFrame(step);
      } else {
        // normalize rot
        spinAnim.rot = ((to % (Math.PI*2)) + Math.PI*2) % (Math.PI*2);
        drawWheel(spinAnim.rot);
        spawnConfetti();
        drawFx();
      }
    }
    requestAnimationFrame(step);
  }

  function renderNumbers(){
    const root = document.getElementById('nums');
    if (!root || !state) return;
    const N = Math.max(10, state.numbers_pool || 36);
    const drawn = new Set(state.drawn_numbers || []);
    const last = (state.drawn_numbers || []).slice(-1)[0] ?? null;
    root.innerHTML = '';
    for(let i=1;i<=N;i++){
      const d = document.createElement('div');
      d.className = 'num' + (drawn.has(i) ? ' drawn' : '') + (last === i ? ' last' : '');
      d.textContent = String(i);
      root.appendChild(d);
    }
    setText('lastBadge', `Последнее: ${last ?? '—'}`);
  }

  function updateUI(){
    if (!state) return;
    const drawn = state.drawn_numbers || [];
    const last = drawn.length ? drawn[drawn.length-1] : null;
    setText('hubNum', last ?? '—');
    setText('drawnCount', drawn.length);
    setText('needCount', state.numbers_per_ticket ?? 0);
    setText('poolN', state.numbers_pool ?? '—');

    setText('pillRound', state.week_key ?? '—');
    setText('pillPool', fmtMoney(state.prize_pool));
    setText('pillTicket', fmtMoney(state.ticket_price));
    setText('pillStatus', (state.status || '—'));

    const ds = parseISO(state.draw_starts_at);
    const de = parseISO(state.draw_ends_at);
    if(ds && de){
      // show UTC and MSK (UTC+3)
      const z = (d)=>String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0');
      const msk = (d)=>String((d.getUTCHours()+3)%24).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0');
      setHTML('scheduleLine', `<b>Воскресенье</b> ${z(ds)}–${z(de)} UTC <span style="color:rgba(234,240,255,.75)">(${msk(ds)}–${msk(de)} МСК)</span>`);
    } else {
      setText('scheduleLine', 'Воскресенье (live-режим)');
    }

    renderNumbers();

    // countdown
    const now = new Date();
    if(ds){
      const ms = ds.getTime() - now.getTime();
      if(ms > 0){
        setText('countdown', msToHuman(ms));
      } else {
        setText('countdown', 'идёт');
      }
    } else {
      setText('countdown', '—');
    }
  }

  async function tick(){
    try{
      const res = await fetch('/lottery/state', {cache:'no-store'});
      const data = await res.json();
      state = data;
      updateUI();
      const drawn = data.drawn_numbers || [];
      const len = drawn.length;
      const last = len ? drawn[len-1] : null;

      // animate when new number appears
      if(last !== null && (lastNumber === null || (len > lastLen && last !== lastNumber))){
        lastLen = len;
        lastNumber = last;
        toast(`Выпало число: ${last}`);
        spinToNumber(last);
      } else {
        lastLen = len;
        lastNumber = last;
        drawWheel(spinAnim?.rot ?? 0);
      }
    } catch(e){
      toast('Не удалось обновить состояние (проверьте /lottery/state).');
    }
  }

  resizeCanvases();
  setInterval(tick, 2000);
  tick();
</script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


async def on_startup(app):
    from app.migrate import main as run_migrations
    await init_db()
    try:
        await run_migrations()
    except Exception as e:
        log_info(logger, f"Migrations warning: {e}")
    bot: Bot | None = app.get("bot")
    if bot:
        try:
            await _notify_admins_started(bot)
        except Exception as e:
            log_info(logger, f"Admin notify warning: {e}")
    print("=" * 40)
    print("  BOT STARTED")
    print("=" * 40)
    log_info(logger, "Bot started, DB initialized")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)

    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(on_startup)
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
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
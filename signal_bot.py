"""
Solana Meme Coin Signal Bot
Fitur: Sniper notifikasi, Stop-Loss, Take Profit, Auto-Buy Alert
Data source: DexScreener API
"""

import os
import json
import asyncio
import requests
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

TOKEN = os.environ.get("BOT_TOKEN", "ISI_TOKEN_BOT_KAMU_DISINI")
DATA_FILE = "data.json"

DEXSCREENER_NEW   = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{}"

# ── Data helpers ──────────────────────────────────────────────────────────────

def load_data() -> dict:
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(user_id: int) -> dict:
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"watchlist": {}, "sniper_on": False, "seen_tokens": []}
        save_data(data)
    return data[uid]

def save_user(user_id: int, user_data: dict):
    data = load_data()
    data[str(user_id)] = user_data
    save_data(data)

# ── DexScreener helpers ───────────────────────────────────────────────────────

def get_token_info(contract: str) -> dict | None:
    try:
        r = requests.get(DEXSCREENER_TOKEN.format(contract), timeout=10)
        pairs = r.json().get("pairs") or []
        sol = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol:
            return None
        return max(sol, key=lambda p: float((p.get("volume") or {}).get("h24", 0) or 0))
    except Exception:
        return None

def get_new_solana_tokens() -> list:
    try:
        r = requests.get(DEXSCREENER_NEW, timeout=10)
        profiles = r.json() if isinstance(r.json(), list) else []
        return [p for p in profiles if p.get("chainId") == "solana"]
    except Exception:
        return []

def fmt(n: float) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000: return f"{n/1_000:.2f}K"
    return f"{n:.6f}"

def fmt_price(p: float) -> str:
    if p < 0.000001: return f"${p:.10f}"
    if p < 0.001: return f"${p:.8f}"
    return f"${p:.6f}"

def build_gmgn_link(contract: str) -> str:
    return f"https://gmgn.ai/sol/token/{contract}"

def build_dex_link(contract: str) -> str:
    return f"https://dexscreener.com/solana/{contract}"

# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Solana Signal Bot*\n\n"
        "Bot ini mengirim notifikasi sinyal trading koin meme Solana.\n"
        "Kamu tetap eksekusi manual di GMGN / Phantom.\n\n"
        "*📋 Menu Perintah:*\n"
        "🎯 /sniper — Aktifkan/nonaktifkan notifikasi koin baru\n"
        "➕ /watch `<contract> <buy_price> <tp%> <sl%>` — Pantau koin\n"
        "📋 /watchlist — Lihat semua koin yang dipantau\n"
        "🗑 /unwatch `<contract>` — Berhenti pantau koin\n"
        "🔍 /price `<contract>` — Cek harga koin\n"
        "❓ /help — Panduan lengkap\n\n"
        "Ketik /help untuk contoh penggunaan."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── /help ─────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Panduan Lengkap*\n\n"

        "*1. Sniper — Notifikasi koin baru listing:*\n"
        "`/sniper` → toggle on/off\n"
        "Bot otomatis cek listing baru tiap 2 menit.\n\n"

        "*2. Pantau koin (watchlist):*\n"
        "`/watch <contract> <harga_beli> <target_profit_%> <stop_loss_%>`\n\n"
        "Contoh:\n"
        "`/watch ABC...xyz 0.00001 50 20`\n"
        "Artinya:\n"
        "• Harga beli: $0.00001\n"
        "• Take profit: +50% → notif saat harga naik 50%\n"
        "• Stop loss: -20% → notif saat harga turun 20%\n\n"

        "*3. Auto-buy alert:*\n"
        "Otomatis aktif saat kamu /watch koin.\n"
        "Bot notif jika harga naik 10%, 25%, 50% dari harga beli.\n\n"

        "*4. Cek harga:*\n"
        "`/price <contract>`\n\n"

        "💡 Contract address bisa dicopy dari GMGN atau DexScreener."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── /sniper ───────────────────────────────────────────────────────────────────

async def sniper_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    user["sniper_on"] = not user.get("sniper_on", False)
    save_user(uid, user)

    if user["sniper_on"]:
        await update.message.reply_text(
            "🎯 *Sniper AKTIF!*\n\nBot akan mengirim notifikasi setiap ada koin Solana baru listing di DexScreener.\n\n"
            "Ketik /sniper lagi untuk menonaktifkan.", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🔕 *Sniper NONAKTIF.*", parse_mode="Markdown")

# ── /watch ────────────────────────────────────────────────────────────────────

async def watch_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) != 4:
        await update.message.reply_text(
            "❌ Format salah!\n`/watch <contract> <harga_beli> <tp_%> <sl_%>`\n\n"
            "Contoh: `/watch ABC...xyz 0.00001 50 20`", parse_mode="Markdown"
        )
        return

    contract = args[0]
    try:
        buy_price = float(args[1])
        tp_pct    = float(args[2])
        sl_pct    = float(args[3])
    except ValueError:
        await update.message.reply_text("❌ Harga, TP, dan SL harus berupa angka.")
        return

    msg = await update.message.reply_text("⏳ Mengambil data token...")
    info = get_token_info(contract)
    if not info:
        await msg.edit_text("❌ Token tidak ditemukan di Solana / DexScreener.")
        return

    base   = info.get("baseToken", {})
    symbol = base.get("symbol", "???")
    name   = base.get("name", "Unknown")

    tp_price = buy_price * (1 + tp_pct / 100)
    sl_price = buy_price * (1 - sl_pct / 100)
    current  = float(info.get("priceUsd", 0) or 0)

    uid  = update.effective_user.id
    user = get_user(uid)
    user["watchlist"][contract] = {
        "symbol":    symbol,
        "name":      name,
        "buy_price": buy_price,
        "tp_price":  tp_price,
        "sl_price":  sl_price,
        "tp_pct":    tp_pct,
        "sl_pct":    sl_pct,
        "alerted_tp": False,
        "alerted_sl": False,
        "alerted_buy_10":  False,
        "alerted_buy_25":  False,
        "alerted_buy_50":  False,
    }
    save_user(uid, user)

    text = (
        f"✅ *{name} (${symbol})* ditambahkan ke watchlist!\n\n"
        f"💰 Harga beli: {fmt_price(buy_price)}\n"
        f"📈 Take Profit (+{tp_pct}%): {fmt_price(tp_price)}\n"
        f"🛑 Stop Loss (-{sl_pct}%): {fmt_price(sl_price)}\n"
        f"📊 Harga sekarang: {fmt_price(current)}\n\n"
        f"Bot akan kirim notifikasi otomatis saat:\n"
        f"• Harga naik 10%, 25%, 50% dari harga beli\n"
        f"• Take profit tercapai\n"
        f"• Stop loss tercapai"
    )
    await msg.edit_text(text, parse_mode="Markdown")

# ── /watchlist ────────────────────────────────────────────────────────────────

async def watchlist_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)
    wl   = user.get("watchlist", {})

    if not wl:
        await update.message.reply_text(
            "📭 Watchlist kosong.\nGunakan /watch untuk menambah koin."
        )
        return

    msg = await update.message.reply_text("⏳ Memuat data harga terbaru...")
    lines = ["📋 *Watchlist Kamu*\n"]

    for contract, coin in wl.items():
        info    = get_token_info(contract)
        current = float(info.get("priceUsd", 0) or 0) if info else 0
        buy     = coin["buy_price"]
        pnl_pct = ((current - buy) / buy * 100) if buy else 0
        emoji   = "🟢" if pnl_pct >= 0 else "🔴"

        lines.append(
            f"*{coin['name']}* (${coin['symbol']})\n"
            f"  Beli: {fmt_price(buy)} | Skrg: {fmt_price(current)}\n"
            f"  {emoji} PnL: {pnl_pct:+.1f}%\n"
            f"  🎯 TP: {fmt_price(coin['tp_price'])} (+{coin['tp_pct']}%)\n"
            f"  🛑 SL: {fmt_price(coin['sl_price'])} (-{coin['sl_pct']}%)\n"
            f"  [DEX]({build_dex_link(contract)}) | [GMGN]({build_gmgn_link(contract)})\n"
        )

    await msg.edit_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)

# ── /unwatch ──────────────────────────────────────────────────────────────────

async def unwatch_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: `/unwatch <contract>`", parse_mode="Markdown")
        return
    contract = ctx.args[0]
    uid  = update.effective_user.id
    user = get_user(uid)

    if contract not in user.get("watchlist", {}):
        await update.message.reply_text("❌ Koin tidak ada di watchlist.")
        return

    symbol = user["watchlist"][contract]["symbol"]
    del user["watchlist"][contract]
    save_user(uid, user)
    await update.message.reply_text(f"🗑 *${symbol}* dihapus dari watchlist.", parse_mode="Markdown")

# ── /price ────────────────────────────────────────────────────────────────────

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: `/price <contract>`", parse_mode="Markdown")
        return
    contract = ctx.args[0]
    msg  = await update.message.reply_text("⏳ Mengambil harga...")
    info = get_token_info(contract)
    if not info:
        await msg.edit_text("❌ Token tidak ditemukan.")
        return

    base   = info.get("baseToken", {})
    symbol = base.get("symbol", "???")
    name   = base.get("name", "Unknown")
    price  = float(info.get("priceUsd", 0) or 0)
    chg    = info.get("priceChange", {})
    h1     = chg.get("h1", 0) or 0
    h24    = chg.get("h24", 0) or 0
    vol24  = float((info.get("volume") or {}).get("h24", 0) or 0)
    liq    = float((info.get("liquidity") or {}).get("usd", 0) or 0)
    mcap   = float(info.get("marketCap", 0) or 0)

    text = (
        f"🔍 *{name}* (${symbol})\n\n"
        f"💵 Harga: `{fmt_price(price)}`\n"
        f"📈 1j: {h1:+.1f}% | 24j: {h24:+.1f}%\n"
        f"📊 Volume 24j: ${fmt(vol24)}\n"
        f"💧 Likuiditas: ${fmt(liq)}\n"
        f"🏦 Market Cap: ${fmt(mcap)}\n\n"
        f"[DexScreener]({build_dex_link(contract)}) | [GMGN]({build_gmgn_link(contract)})"
    )
    await msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ── Background jobs ───────────────────────────────────────────────────────────

async def check_watchlist(app):
    """Cek harga semua koin di watchlist semua user, kirim alert jika perlu."""
    data = load_data()
    changed = False

    for uid_str, user in data.items():
        wl = user.get("watchlist", {})
        for contract, coin in wl.items():
            info = get_token_info(contract)
            if not info:
                continue
            current = float(info.get("priceUsd", 0) or 0)
            buy     = coin["buy_price"]
            if buy == 0:
                continue
            pnl_pct = (current - buy) / buy * 100
            symbol  = coin["symbol"]
            name    = coin["name"]

            async def send(text):
                await app.bot.send_message(
                    chat_id=int(uid_str), text=text,
                    parse_mode="Markdown", disable_web_page_preview=True
                )

            # Auto-buy alerts (10%, 25%, 50%)
            for lvl, key in [(10, "alerted_buy_10"), (25, "alerted_buy_25"), (50, "alerted_buy_50")]:
                if pnl_pct >= lvl and not coin.get(key):
                    coin[key] = True
                    changed = True
                    await send(
                        f"📈 *Auto-Buy Alert — {name} (${symbol})*\n\n"
                        f"Harga naik *+{lvl}%* dari harga belimu!\n"
                        f"Harga sekarang: `{fmt_price(current)}`\n"
                        f"Harga beli: `{fmt_price(buy)}`\n\n"
                        f"[DEX]({build_dex_link(contract)}) | [GMGN]({build_gmgn_link(contract)})"
                    )

            # Take profit alert
            if current >= coin["tp_price"] and not coin.get("alerted_tp"):
                coin["alerted_tp"] = True
                changed = True
                await send(
                    f"🎯 *TAKE PROFIT — {name} (${symbol})*\n\n"
                    f"Target profit *+{coin['tp_pct']}%* tercapai!\n"
                    f"Harga sekarang: `{fmt_price(current)}`\n"
                    f"Target TP: `{fmt_price(coin['tp_price'])}`\n\n"
                    f"💡 Pertimbangkan untuk jual sebagian atau semua!\n\n"
                    f"[DEX]({build_dex_link(contract)}) | [GMGN]({build_gmgn_link(contract)})"
                )

            # Stop loss alert
            if current <= coin["sl_price"] and not coin.get("alerted_sl"):
                coin["alerted_sl"] = True
                changed = True
                await send(
                    f"🛑 *STOP LOSS — {name} (${symbol})*\n\n"
                    f"Harga turun *-{coin['sl_pct']}%* dari harga belimu!\n"
                    f"Harga sekarang: `{fmt_price(current)}`\n"
                    f"Batas SL: `{fmt_price(coin['sl_price'])}`\n\n"
                    f"⚠️ Pertimbangkan untuk cut loss sekarang!\n\n"
                    f"[DEX]({build_dex_link(contract)}) | [GMGN]({build_gmgn_link(contract)})"
                )

    if changed:
        save_data(data)


async def check_sniper(app):
    """Cek token baru listing di Solana, kirim notif ke user yang sniper aktif."""
    data    = load_data()
    tokens  = get_new_solana_tokens()
    changed = False

    for uid_str, user in data.items():
        if not user.get("sniper_on"):
            continue
        seen = set(user.get("seen_tokens", []))

        for token in tokens:
            addr = token.get("tokenAddress", "")
            if not addr or addr in seen:
                continue
            seen.add(addr)
            changed = True

            # Ambil detail dari DexScreener
            info   = get_token_info(addr)
            price  = float(info.get("priceUsd", 0) or 0) if info else 0
            liq    = float((info.get("liquidity") or {}).get("usd", 0) or 0) if info else 0
            mcap   = float(info.get("marketCap", 0) or 0) if info else 0
            symbol = (info.get("baseToken") or {}).get("symbol", "???") if info else "???"
            name   = (info.get("baseToken") or {}).get("name", token.get("description", "Unknown")) if info else token.get("description", "Unknown")

            # Filter: skip token dengan likuiditas sangat rendah (< $1000)
            if liq < 1000:
                continue

            icon = token.get("icon", "")
            text = (
                f"🎯 *SNIPER ALERT — Koin Baru!*\n\n"
                f"*{name}* (${symbol})\n"
                f"📌 `{addr}`\n\n"
                f"💵 Harga: `{fmt_price(price)}`\n"
                f"💧 Likuiditas: ${fmt(liq)}\n"
                f"🏦 Market Cap: ${fmt(mcap)}\n\n"
                f"⚡ Cepat cek sebelum pumping!\n\n"
                f"[DexScreener]({build_dex_link(addr)}) | [GMGN]({build_gmgn_link(addr)})"
            )
            await app.bot.send_message(
                chat_id=int(uid_str), text=text,
                parse_mode="Markdown", disable_web_page_preview=True
            )

        # Simpan hanya 500 token terakhir agar tidak terlalu besar
        user["seen_tokens"] = list(seen)[-500:]

    if changed:
        save_data(data)


async def background_loop(app):
    """Loop utama yang jalan terus di background."""
    while True:
        try:
            await check_watchlist(app)
        except Exception as e:
            print(f"[watchlist error] {e}")
        try:
            await check_sniper(app)
        except Exception as e:
            print(f"[sniper error] {e}")
        await asyncio.sleep(120)  # cek tiap 2 menit


# ── Main ──────────────────────────────────────────────────────────────────────

async def post_init(app):
    asyncio.create_task(background_loop(app))


def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("sniper",    sniper_cmd))
    app.add_handler(CommandHandler("watch",     watch_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CommandHandler("unwatch",   unwatch_cmd))
    app.add_handler(CommandHandler("price",     price_cmd))
    print("✅ Signal Bot berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()

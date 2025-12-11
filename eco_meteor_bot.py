import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone

# ------------- CONFIG ------------ #

# Countdown channel ID – set dynamically by !createmeteor
COUNTDOWN_CHANNEL_ID = None

# Impact time (set by !createmeteor)
TARGET_TIME = None  # type: datetime | None

# Event name
EVENT_NAME = "meteor impact"

# Days before impact when the bot pings everyone
REMINDER_DAYS = {28, 21, 14, 7, 2, 1}

# Hours before impact when the bot pings everyone (within last 48h)
REMINDER_HOURS = {24, 12, 6, 3, 1}

# Meteor emoji / icon
METEOR_ICON = "☄️"

# Channel name once the timer hits zero
FINISHED_NAME = f"{METEOR_ICON} · Impact imminent!"

# --------------------------------- #

intents = discord.Intents.default()
intents.message_content = True  # needed for commands
bot = commands.Bot(command_prefix="!", intents=intents)

# Track which reminders have been sent (resets if bot restarts or impact time changes)
sent_day_reminders = set()
sent_hour_reminders = set()


# ---------- Helpers ---------- #

def format_time(delta):
    """Return a clean countdown string like '10d 4h 32m'."""
    total = int(delta.total_seconds())
    if total < 0:
        total = 0

    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


def parse_datetime_utc(date_str: str, time_str: str) -> datetime:
    """
    Parse 'YYYY-MM-DD' and 'HH:MM' as a UTC datetime.
    Example: 2025-12-31 23:59 -> 2025-12-31T23:59:00+00:00 UTC

    NOTE: In UK winter (GMT) local time == UTC.
    If you want to treat the input as UK local,
    and auto-convert to UTC including BST later,
    we can extend this later.
    """
    year, month, day = map(int, date_str.split("-"))
    hour, minute = map(int, time_str.split(":"))
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------- Events & loop ---------- #

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not update_loop.is_running():
        update_loop.start()


@tasks.loop(minutes=1)
async def update_loop():
    global TARGET_TIME, sent_day_reminders, sent_hour_reminders, COUNTDOWN_CHANNEL_ID

    # If no event or no channel, there is nothing to do
    if TARGET_TIME is None or COUNTDOWN_CHANNEL_ID is None:
        return

    now = datetime.now(timezone.utc)
    remaining = TARGET_TIME - now
    total_seconds = remaining.total_seconds()

    # Fetch countdown channel
    countdown_channel = bot.get_channel(COUNTDOWN_CHANNEL_ID)
    if countdown_channel is None:
        try:
            countdown_channel = await bot.fetch_channel(COUNTDOWN_CHANNEL_ID)
        except Exception as e:
            print("Could not fetch countdown channel:", e)
            return

    announce_channel = countdown_channel  # same channel for messages

    # --- If timer ended ---
    if total_seconds <= 0:
        if countdown_channel and countdown_channel.name != FINISHED_NAME:
            try:
                await countdown_channel.edit(name=FINISHED_NAME)
                print("Set finished channel name.")
            except Exception as e:
                print("Could not rename channel:", e)

        # Optional final ping:
        # try:
        #     await announce_channel.send("@everyone The meteor has impacted! ☄️🔥")
        # except Exception as e:
        #     print("Failed to send final impact message:", e)
        return

    # --- Update channel name ---
    time_str = format_time(remaining)
    new_name = f"{METEOR_ICON} · {time_str} till impact"

    if countdown_channel and countdown_channel.name != new_name:
        try:
            await countdown_channel.edit(name=new_name)
            print(f"Updated channel name to: {new_name}")
        except Exception as e:
            print("Rename failed:", e)

    # --- Day-based reminders ---
    days_remaining = int(total_seconds // 86400)
    if (
        days_remaining in REMINDER_DAYS
        and days_remaining not in sent_day_reminders
        and announce_channel is not None
    ):
        sent_day_reminders.add(days_remaining)
        plural = "" if days_remaining == 1 else "s"
        try:
            await announce_channel.send(
                f"@everyone **{days_remaining} day{plural}** remain until **{EVENT_NAME}** ☄️"
            )
            print(f"Sent day reminder for {days_remaining}d remaining.")
        except Exception as e:
            print("Failed to send day reminder:", e)

    # --- Hour-based reminders (when under 2 days left) ---
    if total_seconds < 2 * 86400:
        hours_remaining = int(round(total_seconds / 3600))
        if (
            hours_remaining in REMINDER_HOURS
            and hours_remaining not in sent_hour_reminders
            and announce_channel is not None
        ):
            sent_hour_reminders.add(hours_remaining)
            plural = "" if hours_remaining == 1 else "s"
            try:
                await announce_channel.send(
                    f"@everyone **{hours_remaining} hour{plural}** remain until **{EVENT_NAME}** ☄️"
                )
                print(f"Sent hour reminder for {hours_remaining}h remaining.")
            except Exception as e:
                print("Failed to send hour reminder:", e)


@update_loop.before_loop
async def before_update_loop():
    await bot.wait_until_ready()


# ---------- Commands ---------- #

@bot.command(name="createmeteor")
@commands.has_permissions(manage_channels=True)
async def create_meteor(
    ctx,
    date: str,
    time: str,
    *,
    name: str = "meteor-impact",
):
    """
    Create meteor event + countdown channel + set impact time.

    Usage:
      !createmeteor YYYY-MM-DD HH:MM
      !createmeteor YYYY-MM-DD HH:MM custom-channel-name
    """
    global COUNTDOWN_CHANNEL_ID, TARGET_TIME, sent_day_reminders, sent_hour_reminders

    # Parse datetime
    try:
        impact_dt = parse_datetime_utc(date, time)
    except Exception:
        await ctx.send(
            "❌ Invalid format.\nUse: `!createmeteor YYYY-MM-DD HH:MM [channel-name]`\n"
            "Example: `!createmeteor 2026-01-20 16:47 meteor-impact`"
        )
        return

    guild = ctx.guild

    # If an old countdown channel exists, try to delete it
    if COUNTDOWN_CHANNEL_ID is not None:
        old_channel = guild.get_channel(COUNTDOWN_CHANNEL_ID)
        if old_channel is not None:
            try:
                await old_channel.delete(reason="Recreating meteor countdown channel")
            except Exception as e:
                print("Failed to delete old countdown channel:", e)

    # Create fresh channel
    new_channel = await guild.create_text_channel(name)
    COUNTDOWN_CHANNEL_ID = new_channel.id

    # Set impact time and reset reminders
    TARGET_TIME = impact_dt
    sent_day_reminders = set()
    sent_hour_reminders = set()

    await ctx.send(
        f"✅ Created meteor event for **{EVENT_NAME}**.\n"
        f"   • Channel: {new_channel.mention}\n"
        f"   • Impact time (UTC): **{TARGET_TIME.isoformat()}**\n"
        f"   • Countdown and reminders are now active."
    )


@bot.command(name="deletemeteor")
@commands.has_permissions(manage_channels=True)
async def delete_meteor(ctx):
    """
    Delete the meteor countdown event and its channel.
    Usage: !deletemeteor
    """
    global COUNTDOWN_CHANNEL_ID, TARGET_TIME, sent_day_reminders, sent_hour_reminders

    if COUNTDOWN_CHANNEL_ID is None and TARGET_TIME is None:
        await ctx.send("There is no active meteor event to delete.")
        return

    guild = ctx.guild
    deleted_channel_name = None

    if COUNTDOWN_CHANNEL_ID is not None:
        channel = guild.get_channel(COUNTDOWN_CHANNEL_ID)
        if channel is not None:
            deleted_channel_name = channel.name
            try:
                await channel.delete(reason="Meteor event deleted")
            except Exception as e:
                print("Failed to delete countdown channel:", e)

    # Reset state
    COUNTDOWN_CHANNEL_ID = None
    TARGET_TIME = None
    sent_day_reminders = set()
    sent_hour_reminders = set()

    msg = "🗑️ Deleted meteor event."
    if deleted_channel_name:
        msg += f" Removed channel **#{deleted_channel_name}**."
    await ctx.send(msg)


@bot.command(name="timeleft")
async def time_left(ctx):
    """
    Show remaining time until impact.
    Usage: !timeleft
    """
    if TARGET_TIME is None:
        await ctx.send("There is no active meteor event. Use `!createmeteor` first.")
        return

    now = datetime.now(timezone.utc)
    remaining = TARGET_TIME - now

    if remaining.total_seconds() <= 0:
        await ctx.send(f"The **{EVENT_NAME}** has already occurred!")
    else:
        await ctx.send(f"☄️ Time until impact: **{format_time(remaining)}**")


@bot.command(name="impact")
async def impact_info(ctx):
    """
    Show the impact date and time.
    Usage: !impact
    """
    if TARGET_TIME is None:
        await ctx.send("There is no active meteor event. Use `!createmeteor` first.")
        return

    # Pretty formats
    iso_str = TARGET_TIME.isoformat()
    pretty = TARGET_TIME.strftime("%Y-%m-%d %H:%M (UTC)")

    await ctx.send(
        f"☄️ Impact date & time for **{EVENT_NAME}**:\n"
        f"   • {pretty}\n"
        f"   • ISO: `{iso_str}`"
    )


# ---------- RUN BOT ---------- #

# ---------- RUN BOT ---------- #

TOKEN = os.getenv("DISCORD_TOKEN")  # read token from environment variable

if not TOKEN or TOKEN.strip() == "":
    raise RuntimeError("Bot token missing! Set DISCORD_TOKEN env var.")

bot.run(TOKEN)


bot.run(TOKEN)

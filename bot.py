from contextlib import nullcontext
from datetime import datetime

import discord
from discord.ext import commands, tasks
import paramiko
import subprocess
from dotenv import load_dotenv
import os
import platform
import requests


# Replace with your bot token and channel ID
load_dotenv()
TOKEN = os.getenv('TOKEN')
CHANNEL_ID_STATUS = int(os.getenv('CHANNEL_ID'))
CHANNEL_ID_LOGINS=int(os.getenv("CHANNEL_ID_LOGIN"))
VPS_IP = os.getenv("VPS_IP")  # Replace with your server's IP
SSH_USERNAME = os.getenv("SSH_USERNAME")  # Replace with your VPS SSH username
SSH_PASSWORD = os.getenv("SSH_PASSWORD")  # Or use SSH private key

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# Function to get CPU and Memory usage via SSH
def get_usage():
    try:
        # Connect to the VPS via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VPS_IP, username=SSH_USERNAME, password=SSH_PASSWORD)

        # Run the 'top' command to get CPU and Memory usage
        stdin, stdout, stderr = ssh.exec_command("top -bn1 | grep -E 'Cpu\\(s\\)|MiB Mem'")
        output = stdout.read().decode('utf-8').strip().splitlines()
        # Parse CPU usage
        cpu_line = output[0]
        cpu_array = cpu_line.split(",")
        cpu_usage=float(cpu_array[0].split(":")[1].strip().replace("%", "").replace("us","").strip())


        # Parse Memory usage
        memory_usage_line = output[1]
        memory_info = memory_usage_line.split(",")
        mem_total = float(memory_info[0].split(":")[1].replace("total", "").strip())
        mem_used = float(memory_info[1].replace("free","").strip())
        memory_usage = float(mem_used / mem_total) * 100  # Memory usage in percentage

        ssh.close()
        return cpu_usage,memory_usage
    except Exception as e:
        print(f"Error getting system usage: {e}")
        return None, None


# Function to generate a progress bar
def generate_progress_bar(percentage, length=20):
    # Convert the percentage to a number of filled blocks
    filled_blocks = int((percentage / 100) * length)
    return f"[{'█' * filled_blocks}{' ' * (length - filled_blocks)}] {percentage:.2f}%"

@bot.command()
async def status(ctx):
   await checkstatus()
   try:
       await ctx.message.delete()
   except discord.Forbidden:
       print("Bot lacks permission to delete messages.")
   except discord.HTTPException as e:
       print(f"Failed to delete message: {e}")


prev_stat_message=None

async def checkstatus():
    global prev_stat_message
    channel = bot.get_channel(CHANNEL_ID_STATUS)
    # Get CPU and Memory usage from VPS via SSH
    cpu_usage, memory_usage = get_usage()

    if cpu_usage is not None and memory_usage is not None:
        # Create progress bars for CPU and Memory
        cpu_progress_bar = generate_progress_bar(cpu_usage)
        memory_progress_bar = generate_progress_bar(memory_usage)

        # Create the message with CPU and Memory usage as progress bars

        embed = discord.Embed(
            title="Server Notification",
            description="Here are the latest updates from your VPS.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Time", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        embed.add_field(name="CPU Usage", value="", inline=False)
        embed.add_field(name="",value=cpu_progress_bar, inline=False)
        embed.add_field(name="Memory Usage", value="", inline=False)
        embed.add_field(name="",value=memory_progress_bar, inline=False)

        if is_server_online(VPS_IP):
            embed.add_field(name="✅ Your VPS is online.",value="")
        else:
            embed.add_field(name="⚠️ **ALERT:** Your VPS appears to be offline! ⚠️", value="")

        embed.set_footer(text="VPS Monitoring Bot")

        if prev_stat_message is not None:
            await prev_stat_message.edit(embed=embed)
        else:
            prev_stat_message=await channel.send(embed=embed)

    # Check if the server is online (ping)


# Periodic monitoring task
@tasks.loop(minutes=5)  # Change interval as needed
async def monitor_vps():
    await checkstatus()

# Event to start the monitoring task
def is_server_online(ip_address):
    try:
        # Detect the OS
        system_platform = platform.system()
        if system_platform == "Windows":
            # Use Windows-compatible ping command
            response = subprocess.run(
                ["ping", "-n", "1", ip_address],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            # Use Unix-compatible ping command
            response = subprocess.run(
                ["ping", "-c", "1", ip_address],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        # Check the response
        return response.returncode == 0  # 0 indicates success
    except Exception as e:
        print(f"Error checking server status: {e}")
        return False

def get_login_events():
    try:
        # Connect to the VPS via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VPS_IP, username=SSH_USERNAME, password=SSH_PASSWORD)

        # Check the auth log for recent login events
        stdin, stdout, stderr = ssh.exec_command("sudo tail -n 20 /var/log/auth.log | grep 'Accepted'", get_pty=True)
        stdin.write(SSH_PASSWORD + "\n")
        stdin.flush()

        output = stdout.read().decode('utf-8').strip()
        ssh.close()  # Close the SSH connection
        # Filter out the bot's own login events
        bot_ip = os.getenv(get_bot_public_ip())  # IP address of the machine running the bot
        filtered_events = [
            line for line in output.splitlines()
            if SSH_USERNAME not in line and (bot_ip not in line if bot_ip else True)
        ]

        return filtered_events
    except Exception as e:
        print(f"Error getting login events: {e}")
        return []


def get_bot_public_ip():
    try:
        response = requests.get("https://api64.ipify.org?format=json")
        response.raise_for_status()
        ip = response.json()["ip"]
        return ip
    except Exception as e:
        print(f"Error retrieving public IP: {e}")
        return None

reported_logins = set()

@tasks.loop(minutes=1)  # Check for logins every minute
async def monitor_logins():
    channel = bot.get_channel(CHANNEL_ID_LOGINS)
    login_events = get_login_events()

    for event in login_events:
        if event not in reported_logins:
            reported_logins.add(event)
            embed = discord.Embed(
                title="Login Notification",
                color=discord.Color.red()
            )
            embed.add_field(name="🔒 New Login", value="**Login Alert:** "+event, inline=False)
            await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    monitor_vps.start()
    monitor_logins.start()


bot.run(TOKEN)

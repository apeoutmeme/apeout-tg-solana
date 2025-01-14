import logging
import asyncio
from typing import Any, Dict
from aiogram import Bot, Dispatcher, types
import aiogram
from aiogram.enums import ParseMode
from aiogram.filters import Command
from datetime import datetime
import random
import os
from pathlib import Path
import json
from datetime import datetime, timedelta
import sys
import requests
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig
from creation import create_token_bundle
from aiohttp import web
from dotenv import load_dotenv
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


load_dotenv()
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f'https://{WEBHOOK_HOST}{WEBHOOK_PATH}'
PORT = int(os.getenv('PORT', 10000))
HOST = '0.0.0.0'  # Important for Render



# Bot Configuration
CHAT_ID = '-1002396701760'  # Your chat ID
API_URL = "https://pumpportal.fun/api"
# Store user private keys (in memory - consider using a secure database in production)
user_wallets = {}


# After load_dotenv()
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
if not WEBHOOK_HOST:
    raise ValueError("WEBHOOK_HOST environment variable is not set")

# Buy announcement templates
BUY_MESSAGES = [
    "🚀 Just aped into this gem! $TOKEN_SYMBOL looking JUICY! 💦",
    "🦍 Ape brain activated! Loading up on $TOKEN_SYMBOL! Time to eat some crayons! 🖍️",
    "💎 Found a hidden gem! $TOKEN_SYMBOL looking primed for takeoff! 🌙",
    "🎯 Target acquired! Just loaded my bags with $TOKEN_SYMBOL! WAGMI! 🚀",
    "🔥 FOMO hitting hard! Had to ape into $TOKEN_SYMBOL! LFG! 🦍"
]

# Initialize bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
active_schedules = {}

async def on_startup(bot: Bot) -> None:
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")


class TradeConfig:
    def __init__(
        self,
        private_key: str,
        rpc_endpoint: str = "https://api.mainnet-beta.solana.com",
        api_endpoint: str = "https://pumpportal.fun/api/trade-local"
    ):
        self.private_key = private_key
        self.rpc_endpoint = rpc_endpoint
        self.api_endpoint = api_endpoint
        self.keypair = Keypair.from_base58_string(private_key)

class SolanaTrader:
    def __init__(self, config: TradeConfig):
        self.config = config
        
    async def execute_trade(
        self,
        action: str,
        mint_address: str,
        amount: int = 0.001,
        denominated_in_sol: bool = True,
        slippage: int = 10,
        priority_fee: float = 0.00001,
        skip_pre_flight: bool = True,
        pool: str = "raydium"
    ) -> Dict[str, Any]:
        """Execute a trade with the given parameters"""
        try:
            trade_payload = {
                "publicKey": str(self.config.keypair.pubkey()),
                "action": action,
                "mint": mint_address,
                "amount": amount,
                "denominatedInSol": str(denominated_in_sol).lower(),
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": pool
            }
            
            logger.info(f"Sending trade request: {trade_payload}")
            
            response = requests.post(
                url=self.config.api_endpoint,
                json=trade_payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            if not response.content:
                raise Exception("Empty response from API")
            
            tx = VersionedTransaction(
                VersionedTransaction.from_bytes(response.content).message,
                [self.config.keypair]
            )
            
            commitment = CommitmentLevel.Confirmed
            config = RpcSendTransactionConfig(preflight_commitment=commitment)
            tx_payload = SendVersionedTransaction(tx, config)
            
            rpc_response = requests.post(
                url=self.config.rpc_endpoint,
                headers={"Content-Type": "application/json"},
                data=tx_payload.to_json()
            )
            rpc_response.raise_for_status()
            
            response_data = rpc_response.json()
            if 'result' not in response_data:
                raise Exception(f"Invalid RPC response: {response_data}")
                
            tx_signature = response_data['result']
            logger.info(f"Transaction sent: https://solscan.io/tx/{tx_signature}")
            
            return {
                "success": True,
                "signature": tx_signature,
                "solscan_url": f"https://solscan.io/tx/{tx_signature}"
            }
            
        except Exception as e:
            logger.error(f"Trade execution failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

@dp.message(Command(commands=['start']))
async def start_command(message: types.Message):
    """Handle start command"""
    welcome_text = (
        "🚀 Welcome to the Solana Trading Bot!\n\n"
        "Commands:\n"
        "/createwallet - Create a new trading wallet\n"
        "/setkey <private_key> - Set your private key\n"
        "/createtoken - Create a new token on Pump.fun\n"
        "/buy <token_address> <amount> - Buy tokens\n"
        "/startschedule <token_address> <amount> - Start hourly DCA\n"
        "/stopschedule <token_address> - Stop DCA\n"
        "/removekey - Remove your private key\n\n"
        "⚠️ Never share your private key with anyone else!"
    )
    await message.reply(welcome_text)

@dp.message(Command(commands=['setkey']))
async def set_private_key(message: types.Message):
    """Handle private key setting"""
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) != 2:
            await message.reply("Usage: /setkey <private_key>")
            return
            
        private_key = parts[1]
        user_id = message.from_user.id
        
        # Validate private key by trying to create a keypair
        try:
            keypair = Keypair.from_base58_string(private_key)
            user_wallets[user_id] = private_key
            # Delete message containing private key for security
            await message.delete()
            await message.answer("✅ Private key set successfully! You can now use /buy and /startschedule commands.")
        except Exception as e:
            await message.reply("❌ Invalid private key format")
            
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command(commands=['removekey']))
async def remove_private_key(message: types.Message):
    """Remove user's private key"""
    user_id = message.from_user.id
    if user_id in user_wallets:
        del user_wallets[user_id]
        await message.reply("✅ Private key removed successfully")
    else:
        await message.reply("❌ No private key found")

@dp.message(Command(commands=['buy']))
async def handle_buy(message: types.Message):
    """Handle buy command"""
    try:
        user_id = message.from_user.id
        if user_id not in user_wallets:
            await message.reply("❌ Please set your private key first using /setkey")
            return
            
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("Usage: /buy <token_address> <amount>")
            return
            
        _, token_address, amount = parts
        amount = float(amount)
        
        # Ask user about pool selection
        pool_msg = await message.reply(
            "Is this token on Pump.fun? (not graduated yet?)\n"
            "Reply with 'yes' or 'no'"
        )
        
        # Wait for user response
        @dp.message()
        async def pool_response(response: types.Message):
            if response.from_user.id != user_id:
                return
                
            pool = "pump" if response.text.lower() == "yes" else "raydium"
            
            # Remove the handler after getting response
            dp.message.handlers.pop()
            
            trader = SolanaTrader(TradeConfig(user_wallets[user_id]))
            result = await trader.execute_trade(
                action="buy",
                mint_address=token_address,
                amount=amount,
                denominated_in_sol=True,
                pool=pool
            )
            
            if result["success"]:
                success_msg = (
                    f"✅ Buy order executed on {pool.upper()}!\n"
                    f"Amount: {amount} SOL\n"
                    f"Token: {token_address}\n"
                    f"TX: {result['solscan_url']}"
                )
                await message.reply(success_msg)
            else:
                await message.reply(f"❌ Trade failed: {result.get('error', 'Unknown error')}")
        dp.message.register(pool_response)   
    except ValueError:
        await message.reply("Invalid amount format")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command(commands=['createwallet']))
async def create_wallet_command(message: types.Message):
    """Handle wallet creation command"""
    try:
        # Create wallet request
        response = requests.post(
            f"{API_URL}/create-wallet",
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        wallet_data = response.json()
        
        # Format wallet info message
        wallet_info = (
            "✅ New wallet created successfully!\n\n"
            f"📤 Public Key: `{wallet_data['walletPublicKey']}`\n"
            f"🔐 Private Key: `{wallet_data['privateKey']}`\n\n"
            "⚠️ IMPORTANT: Keep your private key safe and never share it!\n"
            "You can use /setkey command with this private key to start trading."
        )
        
        # Send wallet info as private message
        await message.reply(
            wallet_info,
            parse_mode=ParseMode.MARKDOWN,
        )
        
        # Try to delete the command message for security
        try:
            await message.delete()
        except:
            pass
            
    except Exception as e:
        await message.reply(f"❌ Error creating wallet: {str(e)}")

@dp.message(Command(commands=['startschedule']))
async def start_schedule(message: types.Message):
    """Start scheduled buying"""
    try:
        user_id = message.from_user.id
        if user_id not in user_wallets:
            await message.reply("❌ Please set your private key first using /setkey")
            return
            
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("Usage: /startschedule <token_address> <amount>")
            return
            
        _, token_address, amount = parts
        amount = float(amount)

        # Ask user about pool selection
        pool_msg = await message.reply(
            "Is this token on Pump.fun? (not graduated yet?)\n"
            "Reply with 'yes' or 'no'"
        )
        
        # Wait for user response
        @dp.message()
        async def pool_response(response: types.Message):
            if response.from_user.id != user_id:
                return
                
            pool = "pump" if response.text.lower() == "yes" else "raydium"
            
            # Remove the handler after getting response
            dp.message.handlers.pop()

            schedule_key = f"{user_id}_{token_address}"
            if schedule_key in active_schedules:
                active_schedules[schedule_key].cancel()

            async def scheduled_task():
                while True:
                    try:
                        trader = SolanaTrader(TradeConfig(user_wallets[user_id]))
                        result = await trader.execute_trade(
                            action="buy",
                            mint_address=token_address,
                            amount=amount,
                            denominated_in_sol=True,
                            pool=pool
                        )
                        
                        if result["success"]:
                            success_msg = (
                                f"✅ Scheduled buy executed on {pool.upper()}!\n"
                                f"Amount: {amount} SOL\n"
                                f"Token: {token_address}\n"
                                f"TX: {result['solscan_url']}"
                            )
                            await bot.send_message(chat_id=message.chat.id, text=success_msg)
                        
                        await asyncio.sleep(3600)  # Sleep for 1 hour
                    except Exception as e:
                        logger.error(f"Schedule error: {e}")
                        await asyncio.sleep(60)  # Sleep for 1 minute on error

            task = asyncio.create_task(scheduled_task())
            active_schedules[schedule_key] = task

            await message.reply(
                f"✅ Scheduled hourly buys started on {pool.upper()}\n"
                f"Amount: {amount} SOL\n"
                f"Token: {token_address}"
            )
        dp.message.register(pool_response)
    except ValueError:
        await message.reply("Invalid amount format")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
@dp.message(Command(commands=['stopschedule']))
async def stop_schedule(message: types.Message):
    """Stop scheduled buying"""
    try:
        user_id = message.from_user.id
        parts = message.text.split()
        if len(parts) != 2:
            await message.reply("Usage: /stopschedule <token_address>")
            return
            
        _, token_address = parts
        schedule_key = f"{user_id}_{token_address}"

        if schedule_key in active_schedules:
            active_schedules[schedule_key].cancel()
            del active_schedules[schedule_key]
            await message.reply(f"✅ Scheduled buys stopped for {token_address}")
        else:
            await message.reply(f"❌ No active schedule found for {token_address}")
            
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@dp.message(Command(commands=['createtoken']))
async def start_token_creation(message: types.Message):
    """Start token creation process"""
    try:
        user_id = message.from_user.id
        if user_id not in user_wallets:
            await message.reply("❌ Please set your private key first using /setkey")
            return
            
        # Start collecting token information
        await message.reply(
            "Let's create your token! Please provide the following information:\n"
            "1. Token Name (e.g., 'My Cool Token')\n"
            "Send your response now:"
        )
        
        # Store user state
        user_data = {
            "step": 1,
            "token_name": "",
            "token_symbol": "",
            "description": "",
            "twitter_url": "",
            "telegram_url": "",
            "website_url": "",
            "image_url": ""
        }
        
        # Create handler for collecting token information
        @dp.message()
        async def collect_token_info(response: types.Message):
            if response.from_user.id != user_id:
                return
                
            nonlocal user_data
            
            try:
                if user_data["step"] == 1:
                    user_data["token_name"] = response.text
                    user_data["step"] = 2
                    await message.reply("2. Token Symbol (e.g., 'COOL'):")
                    
                elif user_data["step"] == 2:
                    user_data["token_symbol"] = response.text
                    user_data["step"] = 3
                    await message.reply("3. Token Description:")
                    
                elif user_data["step"] == 3:
                    user_data["description"] = response.text
                    user_data["step"] = 4
                    await message.reply("4. Twitter URL (or 'none'):")
                    
                elif user_data["step"] == 4:
                    user_data["twitter_url"] = "" if response.text.lower() == "none" else response.text
                    user_data["step"] = 5
                    await message.reply("5. Telegram URL (or 'none'):")
                    
                elif user_data["step"] == 5:
                    user_data["telegram_url"] = "" if response.text.lower() == "none" else response.text
                    user_data["step"] = 6
                    await message.reply("6. Website URL (or 'none'):")
                    
                elif user_data["step"] == 6:
                    user_data["website_url"] = "" if response.text.lower() == "none" else response.text
                    user_data["step"] = 7
                    await message.reply("7. Please send your token image as a photo:")
                    
                elif user_data["step"] == 7 and response.photo:
                    # Get the largest photo version
                    photo = response.photo[-1]
                    file = await bot.get_file(photo.file_id)
                    file_path = file.file_path
                    
                    # Download the image
                    temp_image_path = f"temp_{user_id}.png"
                    await bot.download_file(file_path, destination=temp_image_path)
                    
                    # Create the token
                    try:
                        wallet_keys = [user_wallets[user_id]]  # Using the user's wallet
                        initial_buys = [1785356]  # Default initial buy amount
                        
                        await message.reply("Creating your token... Please wait.")
                        
                        result = await create_token_bundle(
                            token_name=user_data["token_name"],
                            token_symbol=user_data["token_symbol"],
                            description=user_data["description"],
                            twitter_url=user_data["twitter_url"],
                            telegram_url=user_data["telegram_url"],
                            website_url=user_data["website_url"],
                            image_path=temp_image_path,
                            wallet_key=user_wallets[user_id],  # Pass single wallet key
                            initial_buy=0.1  # Set reasonable initial buy amount in SOL
                        )

                        if result.get("success"):
                            await message.reply(
                                "✅ Token created successfully!\n"
                                f"Name: {user_data['token_name']}\n"
                                f"Symbol: {user_data['token_symbol']}\n"
                                f"Token Address: {result.get('token_address')}\n"
                                f"Transaction: {result.get('transaction_url')}"
                            )
                        else:
                            await message.reply(f"❌ Error creating token: {result.get('error', 'Unknown error')}")
                                                
                    except Exception as e:
                        await message.reply(f"❌ Error creating token: {str(e)}")
                    
                    # Remove the handler
                    dp.message.handlers.pop()
                    
            except Exception as e:
                await message.reply(f"❌ Error: {str(e)}")
                
        dp.message.register(collect_token_info)
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

async def health_check(request):
    return web.Response(text="Bot is running!")

async def webhook_debug(request):
    """Handler for GET requests to webhook endpoint - for debugging only"""
    return web.Response(text="Telegram webhook endpoint is working. Please use POST method for actual webhook requests.")

async def main():
    try:
        # Register commands
        await bot.set_my_commands([
            types.BotCommand(command="start", description="Start the bot"),
            types.BotCommand(command="setkey", description="Set your private key"),
            types.BotCommand(command="createwallet", description="Create a new trading wallet"),
            types.BotCommand(command="buy", description="Buy tokens: /buy <address> <amount>"),
            types.BotCommand(command="startschedule", description="Start hourly buys: /startschedule <address> <amount>"),
            types.BotCommand(command="stopschedule", description="Stop hourly buys: /stopschedule <address>"),
            types.BotCommand(command="removekey", description="Remove your private key"),
            types.BotCommand(command="createtoken", description="Create a new token: /createtoken"),
            types.BotCommand(command="webhookinfo", description="Get webhook status information"),
        ])

        # Setup aiohttp application
        app = web.Application()

        # Setup routes
        app.router.add_get("/health", lambda r: web.Response(text="OK"))
        
        # Create webhook handler
        webhook_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        )
        
        # Register webhook handler
        webhook_handler.register(app, path=WEBHOOK_PATH)
        
        # Setup application
        setup_application(app, dp, bot=bot)
        
        # Set webhook
        await bot.delete_webhook()  # Clear any existing webhook
        await bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True
        )
        
        logger.info(f"Setting webhook URL to {WEBHOOK_URL}")
        
        # Start web server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, HOST, PORT)
        await site.start()
        
        logger.info(f"Bot started on {HOST}:{PORT}")
        
        # Log webhook info
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Current webhook info: {webhook_info}")
        
        # Keep the server running
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"Main loop error: {str(e)}")
        raise
    

if __name__ == '__main__':
    asyncio.run(main())

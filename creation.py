import requests
import base58
import logging
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from typing import List, Dict

# Set up loggingo
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
WALLETS = {
    "WALLET_A": { #create coins
        "PRIVATE_KEY": "",
        "RPC_ENDPOINT": "https://api.mainnet-beta.solana.com"
    },
    "WALLET_B": { #create coins 2
        "PRIVATE_KEY": "",
        "RPC_ENDPOINT": "https://api.mainnet-beta.solana.com"
    },
  
}

def create_token_bundle(
    token_name: str,
    token_symbol: str,
    description: str,
    twitter_url: str,
    telegram_url: str,
    website_url: str,
    image_path: str,
    wallet_keys: List[str],
    initial_buys: List[int]
) -> None:
    """
    Creates a token and sends a bundle of transactions to buy it
    """
    try:
        # Initialize signers from provided wallet keys
        signerKeypairs = [
            Keypair.from_base58_string(key) for key in wallet_keys
        ]

        # Generate random keypair for token
        mint_keypair = Keypair()

        # Prepare token metadata
        form_data = {
            'name': token_name,
            'symbol': token_symbol,
            'description': description,
            'twitter': twitter_url,
            'telegram': telegram_url,
            'website': website_url,
            'showName': 'true'
        }

        # Read and prepare image file
        with open(image_path, 'rb') as f:
            file_content = f.read()

        files = {
            'file': (image_path.split('/')[-1], file_content, 'image/png')
        }

        # Upload to IPFS
        logger.info("Uploading metadata to IPFS...")
        metadata_response = requests.post(
            "https://pump.fun/api/ipfs",
            data=form_data,
            files=files
        )
        metadata_response.raise_for_status()
        metadata_uri = metadata_response.json()['metadataUri']

        # Prepare token metadata
        token_metadata = {
            'name': token_name,
            'symbol': token_symbol,
            'uri': metadata_uri
        }

        # Prepare transaction bundle
        bundled_tx_args = []
        
        # Add create transaction
        bundled_tx_args.append({
            'publicKey': str(signerKeypairs[0].pubkey()),
            'action': 'create',
            'tokenMetadata': token_metadata,
            'mint': str(mint_keypair.pubkey()),
            'denominatedInSol': 'false',
            'amount': initial_buys[0],
            'slippage': 10,
            'priorityFee': 0.0005,
            'pool': 'pump'
        })

        # Add buy transactions for additional wallets
        for i in range(1, len(signerKeypairs)):
            bundled_tx_args.append({
                'publicKey': str(signerKeypairs[i].pubkey()),
                'action': 'buy',
                'mint': str(mint_keypair.pubkey()),
                'denominatedInSol': 'false',
                'amount': initial_buys[i],
                'slippage': 50,
                'priorityFee': 0.0001,
                'pool': 'pump'
            })

        # Generate transactions
        logger.info("Generating transaction bundle...")
        response = requests.post(
            "https://pumpportal.fun/api/trade-local",
            headers={"Content-Type": "application/json"},
            json=bundled_tx_args
        )
        response.raise_for_status()

        # Sign transactions
        encoded_transactions = response.json()
        encoded_signed_transactions = []
        tx_signatures = []

        for index, encoded_tx in enumerate(encoded_transactions):
            if bundled_tx_args[index]["action"] == "create":
                signed_tx = VersionedTransaction(
                    VersionedTransaction.from_bytes(base58.b58decode(encoded_tx)).message,
                    [mint_keypair, signerKeypairs[index]]
                )
            else:
                signed_tx = VersionedTransaction(
                    VersionedTransaction.from_bytes(base58.b58decode(encoded_tx)).message,
                    [signerKeypairs[index]]
                )
            
            encoded_signed_transactions.append(base58.b58encode(bytes(signed_tx)).decode())
            tx_signatures.append(str(signed_tx.signatures[0]))

        # Send to Jito MEV
        logger.info("Sending bundle to Jito MEV...")
        jito_response = requests.post(
            "https://mainnet.block-engine.jito.wtf/api/v1/bundles",
            headers={"Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [encoded_signed_transactions]
            }
        )
        jito_response.raise_for_status()

        # Log results
        logger.info(f"Token mint address: {str(mint_keypair.pubkey())}")
        for i, signature in enumerate(tx_signatures):
            logger.info(f'Transaction {i}: https://solscan.io/tx/{signature}')

    except Exception as e:
        logger.error(f"Token creation failed: {str(e)}")
        raise

def main():
    # Example usage
    wallet_keys = [
        WALLETS["WALLET_A"]["PRIVATE_KEY"],
        WALLETS["WALLET_B"]["PRIVATE_KEY"]
    ]
    
    initial_buys = [1785356, 1785356,3564780]  # Amount of tokens to buy for each wallet
    
    create_token_bundle(
        token_name="token",
        token_symbol="$TICK",
        description="",
        twitter_url="",
        telegram_url="",
        website_url="",
        image_path="./folder/image.jpeg",
        wallet_keys=wallet_keys,
        initial_buys=initial_buys
    )

if __name__ == "__main__":
    main()



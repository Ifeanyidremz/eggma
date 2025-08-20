import json
import requests


class CryptoPriceService:
    """Service to fetch real-time crypto prices"""
    
    @staticmethod
    def get_crypto_prices():
        """Fetch current crypto prices from CoinGecko API"""
        try:
            # Free tier - 100 requests per minute
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                'ids': 'bitcoin,ethereum,solana,cardano,polygon,chainlink,uniswap',
                'vs_currencies': 'usd',
                'include_24hr_change': 'true',
                'include_24hr_vol': 'true'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Format the data
            formatted_data = {}
            crypto_mapping = {
                'bitcoin': 'BTC',
                'ethereum': 'ETH', 
                'solana': 'SOL',
                'cardano': 'ADA',
                'polygon': 'MATIC',
                'chainlink': 'LINK',
                'uniswap': 'UNI'
            }
            
            for crypto_id, symbol in crypto_mapping.items():
                if crypto_id in data:
                    formatted_data[symbol] = {
                        'price': data[crypto_id]['usd'],
                        'change_24h': data[crypto_id].get('usd_24h_change', 0),
                        'volume_24h': data[crypto_id].get('usd_24h_vol', 0)
                    }
            
            return formatted_data
            
        except Exception as e:
            print(f"Error fetching crypto prices: {e}")
            # Return mock data if API fails
            return {
                'BTC': {'price': 43500, 'change_24h': 2.5, 'volume_24h': 25000000000},
                'ETH': {'price': 2600, 'change_24h': -1.2, 'volume_24h': 12000000000},
                'SOL': {'price': 65, 'change_24h': 5.8, 'volume_24h': 800000000},
            }

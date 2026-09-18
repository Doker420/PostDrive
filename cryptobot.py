import aiohttp
import asyncio
from typing import Optional, Dict, Any, List

class CryptoBotClient:
    MAINNET_URL = "https://pay.crypt.bot/api"
    TESTNET_URL = "https://testnet-pay.crypt.bot/api"

    def __init__(self, api_token: str, testnet: bool = False):
        self.api_token = api_token
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.headers = {
            "Crypto-Pay-API-Token": self.api_token
        }

    async def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self.api_token:
            return None
        url = f"{self.base_url}/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=self.headers, params=params, json=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    res_json = await resp.json()
                    if res_json.get("ok"):
                        return res_json.get("result")
                    else:
                        print(f"❌ CryptoBot API Error [{endpoint}]: {res_json.get('error')}")
                        return None
        except Exception as e:
            print(f"❌ CryptoBot Connection Exception [{endpoint}]: {e}")
            return None

    async def get_me(self) -> Optional[Dict[str, Any]]:
        return await self._request("GET", "getMe")

    async def create_invoice(self, amount: float, asset: str = "USDT", description: str = "", payload: str = "", expires_in: int = 3600, paid_btn_name: str = "callback", paid_btn_url: str = "") -> Optional[Dict[str, Any]]:
        data = {
            "amount": str(amount),
            "asset": asset.upper(),
            "description": description,
            "payload": payload,
            "expires_in": expires_in
        }
        if paid_btn_name and paid_btn_url:
            data["paid_btn_name"] = paid_btn_name
            data["paid_btn_url"] = paid_btn_url

        return await self._request("POST", "createInvoice", data=data)

    async def get_invoices(self, invoice_ids: Optional[List[int]] = None, status: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        params = {}
        if invoice_ids:
            params["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
        if status:
            params["status"] = status

        result = await self._request("GET", "getInvoices", params=params)
        if result and "items" in result:
            return result["items"]
        return []

    async def check_invoice_paid(self, invoice_id: int) -> bool:
        invoices = await self.get_invoices(invoice_ids=[invoice_id])
        if invoices:
            for inv in invoices:
                if inv.get("invoice_id") == invoice_id and inv.get("status") == "paid":
                    return True
        return False

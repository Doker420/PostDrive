import requests

class FlowPay:
    def __init__(self, api_key, base_url='https://api.example.com/api/v1'):
        self.api_key, self.base_url = api_key, base_url.rstrip('/')
    def create_payment(self, payload, idempotency_key):
        return self._request('POST', '/payments', payload, idempotency_key)
    def get_payment(self, payment_id):
        return self._request('GET', f'/payments/{payment_id}')
    def _request(self, method, path, payload=None, idempotency_key=None):
        headers={'Authorization': f'Bearer {self.api_key}'}
        if idempotency_key: headers['Idempotency-Key'] = idempotency_key
        response=requests.request(method, self.base_url+path, json=payload, headers=headers, timeout=15)
        data=response.json()
        if not response.ok: raise RuntimeError(data.get('detail', 'FlowPay request failed'))
        return data

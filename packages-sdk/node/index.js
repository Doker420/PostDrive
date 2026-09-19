export class FlowPay {
  constructor({apiKey, baseUrl = 'https://api.example.com/api/v1'}) { this.apiKey = apiKey; this.baseUrl = baseUrl; }
  async createPayment(payload, idempotencyKey) { return this.request('/payments', {method:'POST', body: payload, idempotencyKey}); }
  async getPayment(id) { return this.request(`/payments/${id}`); }
  async request(path, {method='GET', body, idempotencyKey}={}) { const r = await fetch(this.baseUrl+path, {method, headers:{Authorization:`Bearer ${this.apiKey}`, ...(body?{'Content-Type':'application/json'}:{}), ...(idempotencyKey?{'Idempotency-Key':idempotencyKey}:{})}, body:body?JSON.stringify(body):undefined}); const data=await r.json(); if(!r.ok) throw new Error(data.detail||'FlowPay request failed'); return data; }
}

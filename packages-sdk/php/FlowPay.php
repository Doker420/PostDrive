<?php
final class FlowPay {
    public function __construct(private string $apiKey, private string $baseUrl = 'https://api.example.com/api/v1') {}
    public function createPayment(array $payload, string $idempotencyKey): array { return $this->request('POST', '/payments', $payload, $idempotencyKey); }
    public function getPayment(string $id): array { return $this->request('GET', '/payments/'.$id); }
    private function request(string $method, string $path, ?array $payload = null, ?string $idempotencyKey = null): array {
        $headers=['Authorization: Bearer '.$this->apiKey, 'Content-Type: application/json'];
        if ($idempotencyKey) $headers[]='Idempotency-Key: '.$idempotencyKey;
        $ch=curl_init(rtrim($this->baseUrl,'/').$path); curl_setopt_array($ch,[CURLOPT_CUSTOMREQUEST=>$method,CURLOPT_HTTPHEADER=>$headers,CURLOPT_RETURNTRANSFER=>true,CURLOPT_TIMEOUT=>15,CURLOPT_POSTFIELDS=>$payload?json_encode($payload):null]); $body=curl_exec($ch); $code=curl_getinfo($ch,CURLINFO_HTTP_CODE); curl_close($ch); $data=json_decode($body,true); if($code<200||$code>=300) throw new RuntimeException($data['detail']??'FlowPay request failed'); return $data;
    }
}

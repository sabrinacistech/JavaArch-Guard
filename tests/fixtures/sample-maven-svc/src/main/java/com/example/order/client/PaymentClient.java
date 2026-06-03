package com.example.order.client;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "payments", url = "${payments.url}")
public interface PaymentClient {

    @CircuitBreaker(name = "payments")
    @Retry(name = "payments")
    @PostMapping("/charge")
    PaymentResponse charge(@RequestBody PaymentRequest request);

    PaymentResponse refund(PaymentRequest request);
}

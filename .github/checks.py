import os
import sys
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import iftar_sayaci


def new_model(threshold=3, reset_timeout=30):
    model = object.__new__(iftar_sayaci.IftarModel)
    model._circuit_breaker_state = "closed"
    model._failure_count = 0
    model._failure_threshold = threshold
    model._circuit_breaker_reset_timeout = reset_timeout
    model._circuit_breaker_open_until = 0.0
    model._circuit_breaker_lock = threading.Lock()
    model._rate_limit_interval = 0.0
    model._last_api_call = 0.0
    model._rate_limit_lock = threading.Lock()
    model.DEFAULT_RETRIES = 1
    model.BACKOFF_FACTOR = 2
    model.DEFAULT_TIMEOUT = 5
    model.log_message = lambda message: None
    return model


def failing_session():
    def get(url, timeout=None, headers=None):
        raise requests.ConnectionError("offline")
    return types.SimpleNamespace(get=get)


def same(actual, expected, label):
    if actual != expected:
        raise AssertionError(label + ": " + repr(actual) + " != " + repr(expected))


def opens_at_the_threshold():
    model = new_model()
    model._istek_sonucunu_isle(basarili=False)
    model._istek_sonucunu_isle(basarili=False)
    same(model._circuit_breaker_state, "closed", "stays closed below the threshold")
    model._istek_sonucunu_isle(basarili=False)
    same(model._circuit_breaker_state, "open", "opens at the threshold")


def an_open_breaker_is_not_reopened():
    model = new_model()
    for _ in range(3):
        model._istek_sonucunu_isle(basarili=False)
    deadline = model._circuit_breaker_open_until
    for _ in range(5):
        model._istek_sonucunu_isle(basarili=False)
    same(model._circuit_breaker_open_until, deadline, "the open window does not slide")
    same(model._failure_count, 3, "the failure count stays pinned at the threshold")


def a_skipped_call_is_not_a_failure():
    model = new_model()
    model.GLOBAL_SESSION = failing_session()
    for _ in range(3):
        try:
            model.perform_request_with_retry("https://example.invalid/x")
        except iftar_sayaci.APIError:
            pass
    same(model._circuit_breaker_state, "open", "three failed requests open the breaker")
    deadline = model._circuit_breaker_open_until
    for _ in range(3):
        try:
            model.perform_request_with_retry("https://example.invalid/x")
        except iftar_sayaci.APIError:
            pass
    same(model._circuit_breaker_open_until, deadline, "a skipped call does not extend the wait")


def the_probe_decides_the_next_state():
    model = new_model(reset_timeout=0)
    for _ in range(3):
        model._istek_sonucunu_isle(basarili=False)
    model._circuit_breaker_state = "half-open"
    model._istek_sonucunu_isle(basarili=False)
    same(model._circuit_breaker_state, "open", "a failed probe reopens the breaker")
    same(model._failure_count, 3, "a failed probe leaves the count at the threshold")
    model._circuit_breaker_state = "half-open"
    model._istek_sonucunu_isle(basarili=True)
    same(model._circuit_breaker_state, "closed", "a successful probe closes the breaker")
    same(model._failure_count, 0, "a successful probe clears the count")


def main():
    checks = (
        opens_at_the_threshold,
        an_open_breaker_is_not_reopened,
        a_skipped_call_is_not_a_failure,
        the_probe_decides_the_next_state,
    )
    for check in checks:
        try:
            check()
        except AssertionError as error:
            print("::error::" + check.__name__ + " failed: " + str(error))
            sys.exit(1)
        print(check.__name__ + " passed")


main()

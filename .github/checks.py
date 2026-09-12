import datetime
import logging
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


def new_view(developer_mode):
    view = object.__new__(iftar_sayaci.IftarView)
    view.model = types.SimpleNamespace(DEVELOPER_MODE=developer_mode)
    return view


def the_window_is_saved_at_the_height_it_was_left_at():
    modes = ((False, iftar_sayaci.WIN_HEIGHT_NORMAL), (True, iftar_sayaci.WIN_HEIGHT_DEV))
    for developer_mode, asgari in modes:
        view = new_view(developer_mode)
        same(view._asgari_yukseklik(), asgari, "the smallest height the window is allowed to take")
        for height in (asgari, asgari + 1, asgari + 210):
            view.windowed_geometry = "965x" + str(height) + "+100+100"
            same(view._kaydedilecek_geometri(), view.windowed_geometry, "the height the window was left at is the height that is saved")


class FakeWidget:
    def __init__(self):
        self.values = {}

    def config(self, **kwargs):
        self.values.update(kwargs)

    def __setitem__(self, key, value):
        self.values[key] = value

    def start(self, *args):
        pass

    def stop(self, *args):
        pass

    def winfo_exists(self):
        return True

    def state(self):
        return "normal"


def counting_view(times):
    view = object.__new__(iftar_sayaci.IftarView)
    view.model = object.__new__(iftar_sayaci.IftarModel)
    view.model.current_ezan_saatleri = times
    view.model._zaman_dilimi = None
    view.model.yesterday_maghrib_str = None
    view.model.tomorrow_imsak_str = None
    view.controller = types.SimpleNamespace(log_message=lambda message: None)
    view.pencere = FakeWidget()
    view.sayac_label = FakeWidget()
    view.yuzde_etiket = FakeWidget()
    view.yuzde_cubugu = FakeWidget()
    view._vakitler_ing = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
    view._label_texts = tuple("vakit" + str(i) for i in range(6))
    view.prayer_labels = [FakeWidget() for _ in range(6)]
    view.prayer_time_labels = [FakeWidget() for _ in range(6)]
    view.default_font = view.bold_font = None
    view._time_parse_cache = {}
    view._tp_key = view._tp_values = None
    view._last_saatler = None
    view._last_vakit_indices = None
    view._pl_state = [None] * 6
    view._pl_time_state = [None] * 6
    view._last_arayuz_minute = (-1, -1)
    view._last_countdown_date = None
    view._countdown_parsed_key = view._countdown_parsed_times = None
    view._countdown_after_id = None
    view._progressbar_mode = None
    view._iftar_celebrated_date = None
    return view


GUNUN_VAKITLERI = {
    "fajr": "05:20", "sunrise": "06:45", "dhuhr": "13:10",
    "asr": "16:35", "maghrib": "19:30", "isha": "20:50",
    "timezone": "Europe/Istanbul",
}


def the_countdown_names_the_time_it_counts_down_to():
    onceki_saat_al = iftar_sayaci.get_utc_now
    onceki_zamanlayici = iftar_sayaci.TkManager.safe_after
    iftar_sayaci.TkManager.safe_after = staticmethod(lambda delay, callback, *a, **k: None)
    try:
        for yarinki_imsak, beklenen in (("05:22", "05:22"), (None, "05:20"), ("", "05:20")):
            view = counting_view(dict(GUNUN_VAKITLERI))
            view.model.tomorrow_imsak_str = yarinki_imsak
            zaman_dilimi = view.model.zaman_dilimi()
            simdi = datetime.datetime(2026, 3, 20, 21, 0, tzinfo=zaman_dilimi)
            iftar_sayaci.get_utc_now = lambda simdi=simdi: simdi.astimezone(datetime.timezone.utc)
            view.update_countdown()
            metin = view.sayac_label.values["text"]
            if "(" + beklenen + ")" not in metin:
                raise AssertionError("the countdown does not name " + beklenen + ": " + metin)
    finally:
        iftar_sayaci.get_utc_now = onceki_saat_al
        iftar_sayaci.TkManager.safe_after = onceki_zamanlayici


def prayer_times_that_no_longer_apply_are_cleared():
    view = counting_view(dict(GUNUN_VAKITLERI))
    onceki_saat_al = iftar_sayaci.get_utc_now
    zaman_dilimi = view.model.zaman_dilimi()
    simdi = datetime.datetime(2026, 3, 20, 14, 0, tzinfo=zaman_dilimi)
    iftar_sayaci.get_utc_now = lambda: simdi.astimezone(datetime.timezone.utc)
    try:
        view.arayuzu_guncelle(dict(GUNUN_VAKITLERI))
        same(view.prayer_time_labels[0].values["text"], "05:20", "the fetched time is shown")
        view.arayuzu_guncelle({})
        same([label.values["text"] for label in view.prayer_time_labels], ["⏳"] * 6, "no time survives the data it came from")
        same(view._last_vakit_indices, None, "no prayer is left marked as the current one")
    finally:
        iftar_sayaci.get_utc_now = onceki_saat_al


def the_log_says_which_line_it_came_from():
    kayitlar = []
    dinleyici = logging.Handler()
    dinleyici.emit = kayitlar.append
    logger = logging.getLogger()
    logger.addHandler(dinleyici)
    try:
        model = object.__new__(iftar_sayaci.IftarModel)
        controller = object.__new__(iftar_sayaci.IftarController)
        model.log_message("modelden")
        model_satiri = sys._getframe().f_lineno - 1
        controller.log_message("kontrolcüden")
        controller_satiri = sys._getframe().f_lineno - 1
        same([kayit.lineno for kayit in kayitlar], [model_satiri, controller_satiri], "the line the message was written on")
    finally:
        logger.removeHandler(dinleyici)


def main():
    checks = (
        opens_at_the_threshold,
        an_open_breaker_is_not_reopened,
        a_skipped_call_is_not_a_failure,
        the_probe_decides_the_next_state,
        the_window_is_saved_at_the_height_it_was_left_at,
        the_countdown_names_the_time_it_counts_down_to,
        prayer_times_that_no_longer_apply_are_cleared,
        the_log_says_which_line_it_came_from,
    )
    for check in checks:
        try:
            check()
        except AssertionError as error:
            print("::error::" + check.__name__ + " failed: " + str(error))
            sys.exit(1)
        print(check.__name__ + " passed")


main()

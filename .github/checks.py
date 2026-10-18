import ast
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


def the_module_update_setting_is_read_before_the_modules_are_imported():
    kaynak = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iftar_sayaci.py")
    with open(kaynak, encoding="utf-8") as dosya:
        agac = ast.parse(dosya.read())
    atamalar = []
    kontrol_satiri = ilk_import_satiri = None
    paketler = ("certifi", "geopy", "ntplib", "requests", "babel", "dotenv", "hijridate")
    for dal in agac.body:
        if isinstance(dal, ast.Assign):
            for hedef in dal.targets:
                if isinstance(hedef, ast.Name) and hedef.id == "CHECK_MODULE_UPDATES":
                    atamalar.append(dal)
        if isinstance(dal, ast.Expr) and isinstance(dal.value, ast.Call):
            islev = dal.value.func
            if isinstance(islev, ast.Attribute) and islev.attr == "ensure_required_modules":
                kontrol_satiri = dal.lineno
        if isinstance(dal, (ast.Import, ast.ImportFrom)) and ilk_import_satiri is None:
            adlar = [ad.name for ad in dal.names]
            etiket = getattr(dal, "module", None) or ",".join(adlar)
            if etiket.split(".")[0] in paketler:
                ilk_import_satiri = dal.lineno
    same(len(atamalar), 1, "the setting is settled in one place")
    if None in (kontrol_satiri, ilk_import_satiri):
        raise AssertionError("the startup steps are no longer where the check looks for them")
    if not isinstance(atamalar[0].value, ast.Call):
        raise AssertionError("the setting is a fixed value instead of one read at startup")
    ayar_satiri = atamalar[0].lineno
    if not ayar_satiri < kontrol_satiri < ilk_import_satiri:
        raise AssertionError("the setting is read at line " + str(ayar_satiri) +
                             ", the modules are checked at line " + str(kontrol_satiri) +
                             " and imported at line " + str(ilk_import_satiri))


def the_setting_comes_from_the_settings_file():
    onceki_dizin = iftar_sayaci.BASE_DIR
    dizin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ayar_denemesi")
    os.makedirs(dizin, exist_ok=True)
    yol = os.path.join(dizin, "settings.ini")
    iftar_sayaci.BASE_DIR = dizin
    try:
        for yazilan, beklenen in (("True", True), ("False", False), ("1", True), ("yes", True)):
            with open(yol, "w", encoding="utf-8") as dosya:
                dosya.write("[AYARLAR]\ncheck_module_updates = " + yazilan + "\n")
            same(iftar_sayaci.modul_guncelleme_tercihi(), beklenen, "the setting read back as " + yazilan)
        os.remove(yol)
        same(iftar_sayaci.modul_guncelleme_tercihi(), False, "no settings file means the check stays off")
        with open(yol, "w", encoding="utf-8") as dosya:
            dosya.write("bu bir ayar dosyası değil")
        same(iftar_sayaci.modul_guncelleme_tercihi(), False, "an unreadable settings file leaves the check off")
    finally:
        iftar_sayaci.BASE_DIR = onceki_dizin
        if os.path.exists(yol):
            os.remove(yol)
        os.rmdir(dizin)


def module_probe(frozen, ticked):
    cagrilar = []
    onceki = (iftar_sayaci.CHECK_MODULE_UPDATES, iftar_sayaci.subprocess,
              iftar_sayaci.importlib, getattr(sys, "frozen", None))
    del iftar_sayaci.BASLANGIC_KAYITLARI[:]
    iftar_sayaci.CHECK_MODULE_UPDATES = ticked
    iftar_sayaci.subprocess = types.SimpleNamespace(
        check_call=lambda komut, shell=False: cagrilar.append(
            "pip " + [parca for parca in komut if not parca.startswith("-")][-1]),
        CalledProcessError=onceki[1].CalledProcessError)
    iftar_sayaci.importlib = types.SimpleNamespace(
        import_module=lambda ad: cagrilar.append("import " + ad),
        invalidate_caches=lambda: None)
    if frozen:
        sys.frozen = True
    elif hasattr(sys, "frozen"):
        del sys.frozen
    try:
        iftar_sayaci.ModuleManager.ensure_required_modules(
            [iftar_sayaci.ModuleManager.ModuleInfo("babel", "babel")])
        soylenenler = [mesaj for _, mesaj in iftar_sayaci.BASLANGIC_KAYITLARI]
    finally:
        iftar_sayaci.CHECK_MODULE_UPDATES, iftar_sayaci.subprocess, iftar_sayaci.importlib = onceki[:3]
        if onceki[3] is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = onceki[3]
        del iftar_sayaci.BASLANGIC_KAYITLARI[:]
    return cagrilar, soylenenler


def a_ticked_module_update_check_updates_before_the_import():
    cagrilar, soylenenler = module_probe(frozen=False, ticked=True)
    same(cagrilar, ["pip babel", "import babel"], "the module is updated before it is imported")
    if not soylenenler:
        raise AssertionError("the update check says nothing about what it did")
    cagrilar, soylenenler = module_probe(frozen=False, ticked=False)
    same(cagrilar, ["import babel"], "an unticked check updates nothing")
    same(soylenenler, [], "an unticked check says nothing")


def a_built_in_module_says_why_it_was_not_checked():
    cagrilar, soylenenler = module_probe(frozen=True, ticked=True)
    same(cagrilar, [], "the program does not reach for pip when its modules are built in")
    same(len(soylenenler), 1, "the ticked check explains itself once")
    if "güncellemeleri kontrol edilmedi" not in soylenenler[0]:
        raise AssertionError("the ticked check does not say it checked nothing: " + soylenenler[0])
    cagrilar, soylenenler = module_probe(frozen=True, ticked=False)
    same(soylenenler, [], "an unticked check says nothing")


def startup_lines_reach_the_log_once_it_is_ready():
    kayitlar = []
    dinleyici = logging.Handler()
    dinleyici.emit = lambda kayit: kayitlar.append(kayit.getMessage())
    logger = logging.getLogger()
    logger.addHandler(dinleyici)
    del iftar_sayaci.BASLANGIC_KAYITLARI[:]
    try:
        iftar_sayaci.baslangic_kaydi(logging.INFO, "açılış satırı")
        same(kayitlar, [], "a startup line waits until the log is ready")
        model = object.__new__(iftar_sayaci.IftarModel)
        model.baslangic_kayitlarini_aktar()
        same(kayitlar, ["açılış satırı"], "the waiting line reaches the log")
        same(iftar_sayaci.BASLANGIC_KAYITLARI, [], "a line that reached the log is not sent twice")
    finally:
        logger.removeHandler(dinleyici)
        del iftar_sayaci.BASLANGIC_KAYITLARI[:]


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
        the_module_update_setting_is_read_before_the_modules_are_imported,
        the_setting_comes_from_the_settings_file,
        a_ticked_module_update_check_updates_before_the_import,
        a_built_in_module_says_why_it_was_not_checked,
        startup_lines_reach_the_log_once_it_is_ready,
    )
    for check in checks:
        try:
            check()
        except AssertionError as error:
            print("::error::" + check.__name__ + " failed: " + str(error))
            sys.exit(1)
        print(check.__name__ + " passed")


main()

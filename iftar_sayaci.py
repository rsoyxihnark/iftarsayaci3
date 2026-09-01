import concurrent.futures
import configparser
import functools
import importlib
import importlib.metadata
import io
import logging
import os
import queue
import random
import re
import signal as signal_mod
import site
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkFont
import traceback
import types as types_mod
import unicodedata
import urllib.parse as urllib_parse
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

logging.raiseExceptions = False
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

class StreamToLogger(io.TextIOBase):
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self._yeniden_giris = threading.local()

    def write(self, buf):
        if getattr(self._yeniden_giris, "aktif", False):
            return len(buf)
        self._yeniden_giris.aktif = True
        try:
            for line in buf.rstrip().splitlines():
                self.logger.log(self.level, line.rstrip())
        finally:
            self._yeniden_giris.aktif = False
        return len(buf)

    def flush(self):
        pass

    def isatty(self):
        return False

T = TypeVar("T")

CHECK_MODULE_UPDATES = False

class ModuleManager:
    VALID_PACKAGE_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:[.-][a-zA-Z0-9_]+)*$")

    @dataclass
    class ModuleInfo:
        mod_name: str
        pkg: Optional[str]

    @staticmethod
    def pip_install_command(*args: str) -> List[str]:
        command = [sys.executable, "-m", "pip", "install", *args]
        if sys.prefix == sys.base_prefix:
            command.append("--user")
        return command

    @classmethod
    def install_module(cls, module_info: "ModuleManager.ModuleInfo") -> None:
        pkg = module_info.pkg if module_info.pkg else module_info.mod_name
        if not cls.VALID_PACKAGE_REGEX.match(pkg):
            raise ValueError(f"Geçersiz veya tehlikeli paket adı: {pkg}")
        command = cls.pip_install_command(pkg)
        logging.info("Modül kuruluyor: %s", " ".join(command))
        subprocess.check_call(command, shell=False)
        if "--user" in command:
            kullanici_dizini = site.getusersitepackages()
            if kullanici_dizini not in sys.path:
                sys.path.append(kullanici_dizini)
        importlib.invalidate_caches()
        try:
            importlib.import_module(module_info.mod_name)
            logging.info("Modül '%s' başarıyla kuruldu.", module_info.mod_name)
        except (ImportError, ModuleNotFoundError) as e:
            logging.error("Modül '%s' kurulmasına rağmen import edilemedi: %s", module_info.mod_name, e)
            raise

    @classmethod
    def manage_module(cls, module_info: "ModuleManager.ModuleInfo") -> None:
        try:
            importlib.import_module(module_info.mod_name)
        except ImportError as e:
            logging.error("Modül '%s' import edilemedi (%s). Kurulum deneniyor...", module_info.mod_name, e)
            cls.install_module(module_info)
        if CHECK_MODULE_UPDATES:
            try:
                logging.info("Modül '%s' güncelleniyor.", module_info.mod_name)
                pkg_name = module_info.pkg if module_info.pkg else module_info.mod_name
                subprocess.check_call(cls.pip_install_command("--upgrade", pkg_name))
            except subprocess.CalledProcessError as e:
                logging.error("Modül '%s' güncellemesi başarısız: %s", module_info.mod_name, e)

    @classmethod
    def ensure_required_modules(cls, modules: List["ModuleManager.ModuleInfo"]) -> None:
        if getattr(sys, "frozen", False):
            return
        for mod_info in modules:
            cls.manage_module(mod_info)

required_modules: List[ModuleManager.ModuleInfo] = [
    ModuleManager.ModuleInfo("babel", "babel"),
    ModuleManager.ModuleInfo("certifi", "certifi"),
    ModuleManager.ModuleInfo("geopy", "geopy"),
    ModuleManager.ModuleInfo("hijridate", "hijridate"),
    ModuleManager.ModuleInfo("ntplib", "ntplib"),
    ModuleManager.ModuleInfo("requests", "requests"),
    ModuleManager.ModuleInfo("rich", "rich"),
    ModuleManager.ModuleInfo("tzdata", "tzdata"),
    ModuleManager.ModuleInfo("dotenv", "python-dotenv"),
]

def get_package_version(pkg: str) -> str:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return "bilinmiyor"

ModuleManager.ensure_required_modules(required_modules)

import certifi
import geopy.geocoders
import ntplib
import requests
from babel import dates as babel_dates
from dotenv import load_dotenv
from geopy.extra.rate_limiter import RateLimiter

from hijridate import Gregorian as HicriGregorian

def uygulama_dizini() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = uygulama_dizini()

load_dotenv(os.path.join(BASE_DIR, ".env"))

APP_VERSION = "1.1.2"
GEOPY_MIN_DELAY = 1.1

class TkManager:
    main_instance: Optional[tk.Tk] = None
    _callback_queue = queue.Queue()

    @staticmethod
    def safe_after(delay: int, callback: Callable, *args, context: str = "Unknown", **kwargs) -> Optional[str]:
        if TkManager.main_instance is None:
            logging.error("(%s) Ana Tk örneği mevcut değil (safe_after).", context)
            return None
        if threading.current_thread() is not threading.main_thread():
            TkManager._callback_queue.put((delay, callback, args, kwargs, context))
            return None

        def wrapper():
            try:
                callback(*args, **kwargs)
            except Exception:
                logging.exception("safe_after callback hatası [%s]", context)
        try:
            return TkManager.main_instance.after(delay, wrapper)
        except tk.TclError as e:
            logging.error("safe_after: '%s' zamanlanamadı: %s", context, e)
            return None
    @staticmethod
    def process_callback_queue():
        while True:
            try:
                delay, cb, args, kwargs, context = TkManager._callback_queue.get_nowait()
            except queue.Empty:
                break
            TkManager.safe_after(delay, cb, *args, context=context, **kwargs)
        if TkManager.main_instance and TkManager.main_instance.winfo_exists():
            TkManager.main_instance.after(100, TkManager.process_callback_queue)
        else:
            logging.debug("process_callback_queue: Ana pencere yok, tekrar zamanlanmıyor.")

def run_on_main_thread_global(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)
        else:
            if TkManager.main_instance is not None:
                result_container = []
                error_container = []
                event = threading.Event()
                iptal_edildi = threading.Event()
                def task():
                    if iptal_edildi.is_set():
                        logging.debug("run_on_main_thread_global: %s zaman aşımına uğradığı için atlandı.", func.__name__)
                        return
                    try:
                        result_container.append(safe_invoke(func, *args, **kwargs))
                    except Exception as e_task:
                         error_container.append(e_task)
                         logging.error("Exception in task scheduled by run_on_main_thread_global for %s: %s", func.__name__, e_task, exc_info=True)
                    finally:
                        event.set()
                TkManager.safe_after(0, task, context=f"run_on_main_thread_global:{func.__name__}")
                if not event.wait(timeout=10):
                    iptal_edildi.set()
                    logging.error("Timeout: %s fonksiyonu ana iş parçacığında çalıştırılırken kilitlendi veya zaman aşımına uğradı. (Mevcut thread: %s, Ana thread: %s)", func.__name__, threading.get_ident(), threading.main_thread().ident)
                    return None
                if error_container:
                     logging.error("Function %s executed with error on main thread: %s", func.__name__, error_container[0])
                     return None 
                return result_container[0] if result_container else None
            else:
                logging.error("Main TK instance'ı mevcut değil: %s", func.__name__)
                return None
    return wrapper

def safe_invoke(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.exception("Callback %s sırasında beklenmeyen hata: %s", func.__name__, e)
        if threading.current_thread() is threading.main_thread():
            safe_showerror("Hata", f"Beklenmeyen bir hata oluştu: {e}")
        else:
            logging.error("GUI hata mesajı yalnızca ana iş parçacığında gösterilebilir. Hata: %s", e)

def run_on_main_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        if threading.current_thread() is threading.main_thread():
            return safe_invoke(func, *args, **kwargs)
        view_instance = args[0] if args else None
        if getattr(view_instance, "pencere", None) is None:
            logging.error("Pencere nesnesi bulunamadı, GUI güncellemesi (%s) yapılamıyor.", func.__name__)
            return None
        TkManager.safe_after(
            0,
            lambda: safe_invoke(func, *args, **kwargs),
            context=f"run_on_main_thread:{func.__name__}"
        )
        return None
    return wrapper

@run_on_main_thread_global
def safe_showinfo(title: str, message: str, *args, **kwargs):
    return messagebox.showinfo(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_showerror(title: str, message: str, *args, **kwargs):
    return messagebox.showerror(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_askyesno(title: str, message: str, *args, **kwargs):
    return messagebox.askyesno(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_askstring(title: str, prompt: str, *args, **kwargs) -> Optional[str]:
    return simpledialog.askstring(title, prompt, *args, **kwargs)

def parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)

class APIError(Exception):
    pass

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

def retry_operation(
    operation: Callable[[], T],
    retries: int,
    backoff_factor: int,
    retryable_exceptions: Tuple[Type[Exception], ...] = (APIError, requests.RequestException)
) -> T:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return operation()
        except retryable_exceptions as e:
            last_error = e
            if attempt == retries - 1:
                break
            sleep_time = min((backoff_factor ** attempt) * random.uniform(0.5, 1.5), 10)
            logging.warning(f"{attempt+1}. denemede geçici hata: {e}. {sleep_time:.2f} saniye sonra yeniden deneniyor.")
            time.sleep(sleep_time)
        except Exception as e:
            logging.exception("Retry operation sırasında yeniden denenemeyen istisna oluştu: %s", e)
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Bilinmeyen hata oluştu.")

def get_timezone_from_str(tz_str: Optional[str]) -> tzinfo:
    if tz_str:
        try:
            return zoneinfo.ZoneInfo(tz_str)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            logging.warning("Zaman dilimi '%s' oluşturulamadı: %s. Sistem yerel zaman dilimi kullanılacak.", tz_str, e)
    return get_utc_now().astimezone().tzinfo or timezone.utc

def saat_metni(deger: str) -> str:
    return deger.strip().split(" ")[0][:5]

def sure_hms(saniye: float) -> str:
    toplam = max(0, int(saniye))
    saat, dakika, sn = toplam // 3600, (toplam % 3600) // 60, toplam % 60
    return f"{saat}:{dakika:02d}:{sn:02d}" if saat else f"{dakika:02d}:{sn:02d}"

def sure_hm(saniye: float) -> str:
    toplam = max(0, int(saniye))
    return f"{toplam // 3600:02d}:{(toplam % 3600) // 60:02d}"

def ilerleme_yuzdesi(gecen: float, toplam: float) -> float:
    if toplam <= 0:
        return 0.0
    return max(0.0, min(100.0, (gecen / toplam) * 100))

def ulke_bayragi(alpha_2: str) -> str:
    kod = alpha_2.strip().upper()
    if len(kod) != 2 or not kod.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in kod)

CLEAN_TEXT_RE = re.compile(r'^[\s\u00A0\uFEFF\u200C]+|[\s\u00A0\uFEFF\u200C]+$')
GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")
WIN_HEIGHT_NORMAL = 650
WIN_HEIGHT_DEV = 860


DEFAULT_SETTINGS = {
    "konum": "İzmir, Turkey",
    "enlem": "38.4237",
    "boylam": "27.1428",
    "metod": "13",
    "check_module_updates": "False",
    "DEVELOPER_MODE": "False",
}

class ConfigManager:
    def __init__(self, path: str) -> None:
        self.path: str = path
        self._lock = threading.RLock()
        self.config: configparser.ConfigParser = configparser.ConfigParser(interpolation=None)
        self.load()
    def reset_to_defaults(self) -> None:
        self.config = configparser.ConfigParser(interpolation=None)
        self.config["AYARLAR"] = dict(DEFAULT_SETTINGS)
    def load(self) -> None:
        with self._lock:
            if not os.path.exists(self.path):
                logging.info("Ayar dosyası bulunamadı; varsayılan ayarlar yükleniyor.")
                self.reset_to_defaults()
                self.save()
                return
            try:
                self.config.read(self.path, encoding="utf-8")
                if "AYARLAR" not in self.config or not self.config["AYARLAR"]:
                    logging.info("Ayarlar bölümü eksik veya boş; varsayılan ayarlar yazılıyor.")
                    self.config["AYARLAR"] = dict(DEFAULT_SETTINGS)
                    self.save()
            except (configparser.Error, OSError, UnicodeDecodeError) as e:
                logging.error("Ayarlar okunurken sorun oluştu: %s", e)
                try:
                    backup_path = self.path + f".backup_{int(time.time())}"
                    os.replace(self.path, backup_path)
                    logging.info("Bozuk ayar dosyası yedeklendi: %s", backup_path)
                except OSError as oe:
                    logging.error("Bozuk ayar dosyası yedeklenemedi: %s", oe)
                self.reset_to_defaults()
                self.save()
                logging.info("Ayarlar sıfırlandı; varsayılan yapı yüklendi.")
    def get(self, key: str, default: str = "") -> str:
        with self._lock:
            return self.config["AYARLAR"].get(key, default)
    def set(self, key: str, value: str) -> None:
        with self._lock:
            self.config["AYARLAR"][key] = value
    def save(self) -> None:
        with self._lock:
            try:
                gecici = self.path + ".tmp"
                with open(gecici, "w", encoding="utf-8") as configfile:
                    self.config.write(configfile)
                os.replace(gecici, self.path)
            except (OSError, configparser.Error) as e:
                logging.error("Konfigürasyon kaydedilemedi: %s", e)

class IftarModel:
    def __init__(self, base_dir: str, default_timeout: int, short_timeout: int, default_retries: int, backoff_factor: int) -> None:
        self.BASE_DIR: str = base_dir
        self.LOG_FILE: str = os.path.join(self.BASE_DIR, "activity.log")
        self.SETTINGS_PATH: str = os.path.join(self.BASE_DIR, "settings.ini")
        self.log_buffer: queue.Queue = queue.Queue(maxsize=2000)
        self.setup_logging()
        self.config_manager = ConfigManager(self.SETTINGS_PATH)
        self.DEVELOPER_MODE: bool = parse_bool(self.config_manager.get("DEVELOPER_MODE", "False"))
        self.DEFAULT_LOCATION: str = DEFAULT_SETTINGS["konum"]
        self.DEFAULT_LATITUDE: float = float(DEFAULT_SETTINGS["enlem"])
        self.DEFAULT_LONGITUDE: float = float(DEFAULT_SETTINGS["boylam"])
        self.DEFAULT_METHOD: str = DEFAULT_SETTINGS["metod"]
        self.current_location: str = ""
        self.current_latitude: Optional[float] = None
        self.current_longitude: Optional[float] = None
        self.current_method: str = ""
        self.DEFAULT_TIMEOUT: int = default_timeout
        self.SHORT_TIMEOUT: int = short_timeout
        self.DEFAULT_RETRIES: int = default_retries
        self.BACKOFF_FACTOR: int = backoff_factor
        self.AUTO_LOCATION_TIMEOUT: int = 20
        self.CONTACT_INFO: str = os.getenv("APP_CONTACT", "").strip()
        self.GLOBAL_SESSION: requests.Session = requests.Session()
        self.GLOBAL_SESSION.verify = certifi.where()
        self.GEOPY_USER_AGENT: str = self._kullanici_ajani()
        self.GLOBAL_SESSION.headers.update({"User-Agent": self.GEOPY_USER_AGENT, "Accept": "application/json"})
        self.IPINFO_API_KEY: Optional[str] = os.getenv("IPINFO_API_KEY", "").strip()
        self._circuit_breaker_state = "closed"
        self._failure_count = 0
        self._failure_threshold = 3
        self._circuit_breaker_reset_timeout = 30
        self._circuit_breaker_open_until = 0.0
        self._circuit_breaker_lock = threading.Lock()
        self._rate_limit_interval = 0.20
        self._last_api_call = 0.0
        self._rate_limit_lock = threading.Lock()
        self._ezan_cache: Dict[Any, Dict[str, str]] = {}
        self._ezan_cache_lock = threading.RLock()
        self._imsakiye_cache: Dict[Any, List] = {}
        self._imsakiye_cache_lock = threading.RLock()
        self._adres_cache: Dict[Tuple[float, float, str], Any] = {}
        self._adres_cache_lock = threading.RLock()
        self.current_ezan_saatleri: Dict[str, str] = {}
        self.current_ezan_anahtari: Optional[tuple] = None
        self._zaman_dilimi: Optional[tzinfo] = None
        self._zaman_dilimi_str: Optional[str] = None
        self.yesterday_maghrib_str: Optional[str] = None
        self.tomorrow_imsak_str: Optional[str] = None
        self._ntp_cache: Optional[datetime] = None
        self._ntp_cache_time: float = 0.0
        self._ntp_lock = threading.RLock()
        self.emojiler: List[str] = ["🌙", "🌅", "☀️", "⛅", "🌆", "🌃"]
        self._hijri_month_cache_val: Optional[int] = None
        self._hijri_month_cache_date: Optional[object] = None
        self._hijri_cache_lock = threading.RLock()
        self._hicri_header_cache_val: Optional[str] = None
        self._hicri_header_cache_date: Optional[object] = None
        max_workers = min(8, max(4, (os.cpu_count() or 1) * 2))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="iftar")
        self.geolocator = geopy.geocoders.Nominatim(user_agent=self.GEOPY_USER_AGENT, timeout=5)
        self._geocode = RateLimiter(self.geolocator.geocode, min_delay_seconds=GEOPY_MIN_DELAY, max_retries=0, swallow_exceptions=False)
        self._reverse = RateLimiter(self.geolocator.reverse, min_delay_seconds=GEOPY_MIN_DELAY, max_retries=0, swallow_exceptions=False)
        self.set_excepthook()
        self.initialize_settings()
    def _kullanici_ajani(self) -> str:
        if self.CONTACT_INFO:
            return f"iftar-sayaci/{APP_VERSION} ({self.CONTACT_INFO})"
        logging.warning(
            "APP_CONTACT ortam değişkeni tanımlı değil. Nominatim (OpenStreetMap) kullanım şartları "
            "iletişim bilgisi içeren bir User-Agent istiyor; .env dosyanıza APP_CONTACT=eposta@ornek.com ekleyin."
        )
        return f"iftar-sayaci/{APP_VERSION}"
    def setup_logging(self) -> None:
        original_stdout = sys.stdout
        self.terminal_stream = original_stdout
        log_queue = queue.Queue(-1)
        from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
        queue_handler = QueueHandler(log_queue)
        queue_handler.setLevel(logging.INFO)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.handlers = []
        logger.addHandler(queue_handler)
        file_handler = RotatingFileHandler(self.LOG_FILE, mode="a", maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_format_str = "%(asctime)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]"
        file_formatter = logging.Formatter(fmt=file_format_str, datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(file_formatter)
        destination_handlers = [file_handler]
        rich_formatter = None
        if original_stdout is None:
            logging.info("Konsol akışı yok (pythonw); terminal çıktısı devre dışı, loglar dosyaya yazılacak.")
        else:
            try:
                from rich.console import Console
                from rich.logging import RichHandler
                rich_console = Console(file=original_stdout, force_terminal=True, color_system="auto")
                rich_handler = RichHandler(
                    level=logging.INFO,
                    show_time=False,
                    show_path=False,
                    rich_tracebacks=True,
                    console=rich_console
                )
                rich_format_str = "%(asctime)s - %(levelname)s - %(message)s [Line:%(lineno)d]"
                rich_formatter = logging.Formatter(rich_format_str, datefmt="%H:%M:%S")
                rich_handler.setFormatter(rich_formatter)
                destination_handlers.append(rich_handler)
            except ImportError:
                logging.warning("Rich kütüphanesi bulunamadı veya yüklenemedi. Terminal çıktısı renksiz olacak.")
            except Exception as e:
                logging.error("RichHandler kurulurken hata oluştu: %s", e)
        self.log_file_handler = file_handler
        buffer_handler = LogBufferHandler(self)
        buffer_formatter = rich_formatter if rich_formatter else file_formatter
        buffer_handler.setFormatter(buffer_formatter)
        destination_handlers.append(buffer_handler)
        self.log_queue_listener = QueueListener(log_queue, *destination_handlers)
        self.log_queue_listener.start()
        sys.stdout = StreamToLogger(logger, logging.INFO)
        sys.stderr = StreamToLogger(logger, logging.ERROR)
        logging.info("Loglama sistemi başlatıldı.")
    def my_excepthook(self, exc_type: type[BaseException], exc_value: BaseException, exc_tb: Optional[types_mod.TracebackType]) -> None:
        hata_mesaji = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("HATA: %s\nLütfen log dosyasını kontrol ediniz.", hata_mesaji)
    def set_excepthook(self) -> None:
        sys.excepthook = self.my_excepthook
    def log_message(self, message: str) -> None:
        logging.info(message)
    def clear_log_file(self) -> None:
        while True:
            try:
                self.log_buffer.get_nowait()
            except queue.Empty:
                break
        if self.terminal_stream is not None and self.terminal_stream.isatty():
            os.system("cls" if os.name == "nt" else "clear")
        handler = self.log_file_handler
        handler.acquire()
        try:
            handler.stream.seek(0)
            handler.stream.truncate()
        except OSError as e:
            logging.exception("Log dosyası temizlenirken sorun oluştu: %s", e)
        finally:
            handler.release()
    def kayitli_koordinatlar(self) -> Optional[Tuple[float, float]]:
        try:
            lat = float(self.config_manager.get("enlem", ""))
            lon = float(self.config_manager.get("boylam", ""))
        except ValueError:
            return None
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
        return None
    def aktif_koordinatlar(self) -> Tuple[float, float]:
        lat = self.current_latitude if self.current_latitude is not None else self.DEFAULT_LATITUDE
        lon = self.current_longitude if self.current_longitude is not None else self.DEFAULT_LONGITUDE
        return lat, lon
    def konumu_kaydet(self, konum: str, lat: float, lon: float) -> None:
        self.config_manager.set("konum", konum)
        self.config_manager.set("enlem", f"{lat:.6f}")
        self.config_manager.set("boylam", f"{lon:.6f}")
        self.config_manager.save()
    def initialize_settings(self) -> None:
        self.current_location = self.config_manager.get("konum", "")
        self.current_method = self.config_manager.get("metod", "")
        if self.current_location:
            coords = self.kayitli_koordinatlar()
            if coords is None:
                coords = self.konum_bilgisini_al(self.current_location)
                if coords:
                    self.konumu_kaydet(self.current_location, coords[0], coords[1])
            if coords:
                self.current_latitude, self.current_longitude = coords
            else:
                logging.warning("Kayıtlı konum ('%s') çözümlenemedi; geçici olarak varsayılan koordinatlar kullanılacak.", self.current_location)
                self.current_latitude, self.current_longitude = self.DEFAULT_LATITUDE, self.DEFAULT_LONGITUDE
        else:
            future = self.executor.submit(self.otomatik_konum_bul)
            try:
                new_location, lat, lon = future.result(timeout=self.AUTO_LOCATION_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logging.warning(
                    "Otomatik konum %d saniyede tamamlanamadı; şimdilik varsayılan konum kullanılacak. "
                    "Sorgu arka planda sürüyor, sonucu bir sonraki açılış için kaydedilecek.",
                    self.AUTO_LOCATION_TIMEOUT
                )
                future.add_done_callback(self._gec_gelen_konumu_kaydet)
                new_location, lat, lon = (None, None, None)
            except Exception as e:
                logging.warning("Otomatik konum alınamadı: %s", e)
                new_location, lat, lon = (None, None, None)
            if new_location:
                self.current_location = new_location
                self.current_latitude, self.current_longitude = lat, lon
                self.konumu_kaydet(new_location, lat, lon)
            else:
                self.current_location = self.DEFAULT_LOCATION
                self.current_latitude, self.current_longitude = self.DEFAULT_LATITUDE, self.DEFAULT_LONGITUDE
        if not self.current_method:
            self.current_method = self.DEFAULT_METHOD
    def _gec_gelen_konumu_kaydet(self, future: "concurrent.futures.Future") -> None:
        try:
            konum, lat, lon = future.result()
        except Exception as e:
            logging.debug("Geciken otomatik konum sorgusu tamamlanamadı: %s", type(e).__name__)
            return
        if not konum or lat is None or lon is None:
            return
        if self.current_location != self.DEFAULT_LOCATION:
            logging.info("Geciken otomatik konum sonucu, bu arada seçilen konumun üzerine yazılmadı.")
            return
        self.konumu_kaydet(konum, lat, lon)
        logging.info("Geciken otomatik konum sonucu bir sonraki açılış için kaydedildi: %s", konum)
    def konum_nesnesi_al(self, lat: float, lon: float, language: str = "en") -> Optional[Any]:
        cache_key = (round(lat, 4), round(lon, 4), language)
        with self._adres_cache_lock:
            if cache_key in self._adres_cache:
                return self._adres_cache[cache_key]
        try:
            location = self._reverse(f"{lat}, {lon}", language=language)
        except Exception as e:
            logging.warning("Ters geokodlama başarısız (%.4f, %.4f): %s", lat, lon, type(e).__name__)
            return None
        if location is None:
            return None
        with self._adres_cache_lock:
            if len(self._adres_cache) > 128:
                self._adres_cache.pop(next(iter(self._adres_cache)))
            self._adres_cache[cache_key] = location
        return location
    @staticmethod
    def remove_diacritics(s: str) -> str:
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    @staticmethod
    def clean_text(text: str) -> str:
        return CLEAN_TEXT_RE.sub('', text)
    def format_active_location(self, lat: Optional[float], lon: Optional[float]) -> str:
        if lat is None or lon is None:
            return "Konum bilgisi yok"
        location = self.konum_nesnesi_al(lat, lon, language="en")
        if location is not None and location.address:
            return location.address
        return f"{lat:.2f}°, {lon:.2f}°"
    def konum_bilgisini_al(self, konum: str) -> Optional[Tuple[float, float]]:
        try:
            self.log_message(f"Konum sorgusu: {konum}")
            location = self._geocode(konum)
            if location:
                self.log_message(f"Konum bulundu: {location.address} ({location.latitude}, {location.longitude})")
                return (location.latitude, location.longitude)
            self.log_message("Belirtilen konum bulunamadı.")
            return None
        except Exception as e:
            logging.warning("Konum sorgulaması sırasında sorun: %s", e)
            return None
    def otomatik_konum_bul(self) -> tuple:
        try:
            self.log_message("Otomatik konum sorgusu başlatılıyor...")
            headers = {"Authorization": f"Bearer {self.IPINFO_API_KEY}"} if self.IPINFO_API_KEY else None
            url = "https://ipinfo.io/json"
            response = self.perform_request_with_retry(url, retries=2, timeout=self.SHORT_TIMEOUT, headers=headers)
            self.log_message(f"ipinfo.io yanıt kodu: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                location_str = data.get("loc", "")
                if location_str:
                    location_parts = location_str.split(",")
                    if len(location_parts) == 2:
                        lat = float(location_parts[0])
                        lon = float(location_parts[1])
                        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                            raise APIError("API tarafından döndürülen koordinatlar geçersiz.")
                        location_obj = self.konum_nesnesi_al(lat, lon)
                        if location_obj:
                            self.log_message(f"Otomatik konum bulundu: {location_obj.address}")
                            return (location_obj.address, lat, lon)
            self.log_message("Otomatik konum alınamadı.")
        except Exception as e:
            logging.warning("Otomatik konum sorgulaması sırasında sorun: %s", e)
        return (None, None, None)
    def zaman_dilimi(self) -> tzinfo:
        tz_str = self.current_ezan_saatleri.get("timezone")
        if self._zaman_dilimi is None or self._zaman_dilimi_str != tz_str:
            self._zaman_dilimi = get_timezone_from_str(tz_str)
            self._zaman_dilimi_str = tz_str
        return self._zaman_dilimi
    def yerel_simdi(self) -> datetime:
        return get_utc_now().astimezone(self.zaman_dilimi())
    def ezan_saatlerini_hesapla(self, enlem: float, boylam: float, method: str, for_date: Optional[str] = None) -> Optional[Dict[str, str]]:
        try:
            date_str = for_date if for_date else self.yerel_simdi().strftime('%d-%m-%Y')
            _cache_key = (enlem, boylam, method, date_str)
            with self._ezan_cache_lock:
                if _cache_key in self._ezan_cache:
                    return self._ezan_cache[_cache_key]
            params = {"latitude": enlem, "longitude": boylam, "method": method}
            url = "https://api.aladhan.com/v1/timings/" + date_str + "?" + urllib_parse.urlencode(params)
            response = self.perform_request_with_retry(url)
            data = response.json()
            if not isinstance(data, dict) or "data" not in data or not isinstance(data.get("data"), dict) or "timings" not in data["data"]:
                error_msg = "API'den geçersiz veya beklenmeyen formatta veri alındı."
                logging.error(error_msg + f" Alınan veri: {str(data)[:200]}...")
                raise APIError(error_msg)
            _result = {k.lower(): saat_metni(v) for k, v in data["data"]["timings"].items()}
            _result["timezone"] = data["data"].get("meta", {}).get("timezone")
            with self._ezan_cache_lock:
                self._ezan_cache[_cache_key] = _result
                _yesterday = (self.yerel_simdi().date() - timedelta(days=1))
                _stale_keys = [k for k in self._ezan_cache if datetime.strptime(k[3], '%d-%m-%Y').date() < _yesterday]
                for _sk in _stale_keys:
                    del self._ezan_cache[_sk]
            return _result
        except (APIError, requests.RequestException) as e:
            logging.error("Ezan saatleri alınamadı: %s", e)
            return None
        except Exception as e:
            logging.exception("Ezan saatleri işlenirken beklenmeyen bir hata oluştu: %s", e)
            return None
    def ramazan_mi(self) -> bool:
        return self.get_current_hijri_month() == 9
    def hicri_tarih_header(self) -> str:
        today = self.yerel_simdi()
        with self._hijri_cache_lock:
            if self._hicri_header_cache_val is not None and self._hicri_header_cache_date == today.date():
                return self._hicri_header_cache_val
        date_str = today.strftime("%d-%m-%Y")
        params = {"date": date_str, "adjustment": 0}
        url = "https://api.aladhan.com/v1/gToH?" + urllib_parse.urlencode(params)
        self.log_message(f"Hicri tarih sorgusu: {url}")
        try:
            response = self.perform_request_with_retry(url)
            data = response.json()
            hicri_gun = data["data"]["hijri"]["day"]
            hicri_yil = data["data"]["hijri"]["year"]
            try:
                ay_no = int(data["data"]["hijri"]["month"]["number"])
            except Exception:
                ay_no = None
            if isinstance(ay_no, int) and 1 <= ay_no <= 12:
                with self._hijri_cache_lock:
                    self._hijri_month_cache_val = ay_no
                    self._hijri_month_cache_date = today.date()
                turkce_ay = HICRI_AY_ISIMLERI[ay_no - 1]
            else:
                hicri_ay_ing = data["data"]["hijri"]["month"]["en"].strip()
                normalized_ay = self.remove_diacritics(hicri_ay_ing).lower()
                turkce_ay = HICRI_AY_ING_MAP.get(normalized_ay, hicri_ay_ing)
            _hicri_result = f"{hicri_gun} {turkce_ay} {hicri_yil} İmsak Takvimi"
            with self._hijri_cache_lock:
                self._hicri_header_cache_val = _hicri_result
                self._hicri_header_cache_date = today.date()
            return _hicri_result
        except Exception as e:
            if getattr(self, "DEVELOPER_MODE", False):
                logging.exception("Hicri tarih bilgileri alınamadı: %s", e)
            else:
                logging.warning("Hicri tarih bilgileri alınamadı: %s", e)
            try:
                hijri_date = HicriGregorian(today.year, today.month, today.day).to_hijri()
                hicri_gun = hijri_date.day
                hicri_ay = hijri_date.month
                hicri_yil = hijri_date.year
            except Exception as conv_e:
                logging.exception("Hijri tarih hesaplanamadı: %s", conv_e)
                with self._hijri_cache_lock:
                    self._hijri_month_cache_val = None
                    self._hijri_month_cache_date = today.date()
                return "İmsak Takvimi"
            hicri_ay_adi = HICRI_AY_ISIMLERI[hicri_ay - 1] if 1 <= hicri_ay <= 12 else str(hicri_ay)
            _hicri_result = f"{hicri_gun} {hicri_ay_adi} {hicri_yil} İmsak Takvimi"
            with self._hijri_cache_lock:
                self._hicri_header_cache_val = _hicri_result
                self._hicri_header_cache_date = today.date()
                if 1 <= hicri_ay <= 12:
                    self._hijri_month_cache_val = hicri_ay
                    self._hijri_month_cache_date = today.date()
            return _hicri_result
    def get_current_hijri_month(self) -> Optional[int]:
        today = self.yerel_simdi().date()
        with self._hijri_cache_lock:
            if self._hijri_month_cache_date == today:
                return self._hijri_month_cache_val
        self.hicri_tarih_header()
        with self._hijri_cache_lock:
            if self._hijri_month_cache_date == today:
                return self._hijri_month_cache_val
        return None
    def imsakiye_takvimini_al(self) -> List[List[str]]:
        now = self.yerel_simdi()
        lat, lon = self.aktif_koordinatlar()
        def takvim_url(yil: int, ay: int) -> str:
            params = {
                "latitude": lat,
                "longitude": lon,
                "method": self.current_method,
                "month": ay,
                "year": yil
            }
            return "https://api.aladhan.com/v1/calendar?" + urllib_parse.urlencode(params)
        url_current = takvim_url(now.year, now.month)
        next_year, next_month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        _imsakiye_key = (round(lat, 6), round(lon, 6), self.current_method, now.date())
        with self._imsakiye_cache_lock:
            data_combined = self._imsakiye_cache.get(_imsakiye_key)
        def takvim_verisi(url: str) -> List:
            response = self.perform_request_with_retry(url)
            gunler = response.json().get("data")
            return gunler if isinstance(gunler, list) else []
        if data_combined is None:
            try:
                hijri_today = HicriGregorian(now.year, now.month, now.day).to_hijri()
                sonraki_ay_basi = datetime(next_year, next_month, 1).date()
                kalan_hicri_gun = hijri_today.month_length() - hijri_today.day
                f_next = None
                if kalan_hicri_gun >= (sonraki_ay_basi - now.date()).days:
                    f_next = self.executor.submit(takvim_verisi, takvim_url(next_year, next_month))
                data_combined = takvim_verisi(url_current)
                if f_next is not None:
                    try:
                        data_combined = data_combined + f_next.result(timeout=self.DEFAULT_TIMEOUT * 3)
                    except concurrent.futures.TimeoutError:
                        f_next.cancel()
                        logging.warning("Sonraki ayın takvimi zamanında alınamadı; yalnızca bu ay listelenecek.")
                    except Exception as e:
                        logging.warning("Sonraki ayın takvimi alınamadı: %s", e)
                for gun in data_combined:
                    gun["_dt"] = datetime.strptime(gun["date"]["gregorian"]["date"], "%d-%m-%Y")
                data_combined.sort(key=lambda gun: gun["_dt"])
            except Exception as e:
                logging.warning("İmsak takvimi alınamadı: %s", e)
                return []
            if data_combined:
                with self._imsakiye_cache_lock:
                    self._imsakiye_cache[_imsakiye_key] = data_combined
                    _stale = [k for k in self._imsakiye_cache if k[3] < now.date()]
                    for _sk in _stale:
                        del self._imsakiye_cache[_sk]
        takvim: List[List[str]] = []
        mevcut_hicri_ay = self.get_current_hijri_month()
        if mevcut_hicri_ay is None:
            self.log_message("Hicri ay bilgileri alınamadı; tüm günler listelenecek.")
        for strict_filter in (True, False):
            if takvim:
                break
            for gun in data_combined:
                gun_tarihi = gun["_dt"]
                if gun_tarihi.date() < now.date():
                    continue
                if strict_filter and mevcut_hicri_ay is not None:
                    gun_hicri_ay = int(gun["date"]["hijri"]["month"]["number"])
                    if gun_hicri_ay != mevcut_hicri_ay:
                        continue
                tarih = babel_dates.format_date(gun_tarihi, "d MMMM yyyy EEEE", locale='tr_TR')
                saatler = [saat_metni(gun["timings"][v]) for v in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")]
                takvim.append([tarih] + saatler)
        self.log_message("İmsak takvimi alındı.")
        return takvim
    def ntp_time_kontrol(self) -> Optional[datetime]:
        with self._ntp_lock:
            if self._ntp_cache is not None:
                gecen = time.monotonic() - self._ntp_cache_time
                if gecen < 30:
                    return self._ntp_cache + timedelta(seconds=gecen)
        try:
            c = ntplib.NTPClient()
            response = c.request('pool.ntp.org', version=3, timeout=3)
            ntp_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        except Exception as e:
            logging.warning("Sistem saati kontrolü yapılamadı: %s", e)
            return None
        with self._ntp_lock:
            self._ntp_cache = ntp_time
            self._ntp_cache_time = time.monotonic()
        return ntp_time
    def sistem_saati_kontrol_alternative(self) -> tuple:
        self.log_message("NTP bağlantısı deneniyor... ⏳")
        ntp_time = self.ntp_time_kontrol()
        if ntp_time is None:
            self.log_message("NTP bağlantısı başarısız.")
            return ("❌", "NTP bağlantısı başarısız")
        sys_time = get_utc_now()
        fark_saniye = abs((ntp_time - sys_time).total_seconds())
        self.log_message(f"NTP Sunucu Saati: {ntp_time.strftime('%Y-%m-%d %H:%M:%S')}, Bilgisayar UTC Saati: {sys_time.strftime('%Y-%m-%d %H:%M:%S')}, Fark: ±{fark_saniye:.2f} saniye")
        if fark_saniye > 60:
            self.log_message("Bilgisayar saati güncel değil.")
            return ("❌", f"Saat güncel değil! (±{fark_saniye:.0f} sn)")
        self.log_message("Bilgisayar saati güncel.")
        return ("✅", "Güncel")
    def api_saglik_durumu(self) -> tuple:
        try:
            baslangic = time.monotonic()
            now = get_utc_now()
            date_str = now.strftime("%d-%m-%Y")
            lat, lon = self.aktif_koordinatlar()
            params = {"latitude": lat, "longitude": lon, "method": self.current_method}
            url = "https://api.aladhan.com/v1/timings/" + date_str + "?" + urllib_parse.urlencode(params)
            response = self.perform_request_with_retry(url, retries=2, timeout=self.SHORT_TIMEOUT)
            gecen = int((time.monotonic() - baslangic) * 1000)
            self.log_message(f"API sağlık kontrolü: {url.split('?')[0]} - {response.status_code} ({gecen} ms)")
            return ("api.aladhan.com", gecen)
        except Exception as e:
            logging.warning("API sağlık kontrolü başarısız: %s", type(e).__name__)
            return ("api.aladhan.com", "bağlantı kurulamadı")
    def perform_request_with_retry(self, url: str, retries: Optional[int] = None, backoff_factor: Optional[int] = None, timeout: Optional[int] = None, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        if retries is None:
            retries = self.DEFAULT_RETRIES
        if backoff_factor is None:
            backoff_factor = self.BACKOFF_FACTOR
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT
        with self._circuit_breaker_lock:
            current_time = time.monotonic()
            if self._circuit_breaker_state == "open":
                if current_time < self._circuit_breaker_open_until:
                    logging.warning(
                        "Circuit breaker açık; API çağrısı atlanıyor (%d saniye kaldı).",
                        round(self._circuit_breaker_open_until - current_time)
                    )
                    raise APIError("Circuit breaker açık. Hatalı uç noktalara aşırı istek gönderilmesini önlemek için API çağrısı atlanıyor.")
                self._circuit_breaker_state = "half-open"
                retries = 1
                logging.info("Circuit breaker yarı açık; tek bir sondaj isteği gönderiliyor.")
            elif self._circuit_breaker_state == "half-open":
                raise APIError("Circuit breaker açık. Sondaj isteği sürerken yeni çağrı gönderilmiyor.")
        def operation() -> requests.Response:
            with self._rate_limit_lock:
                hedef = max(time.monotonic(), self._last_api_call + self._rate_limit_interval)
                self._last_api_call = hedef
            bekleme = hedef - time.monotonic()
            if bekleme > 0:
                time.sleep(bekleme)
            try:
                response = self.GLOBAL_SESSION.get(url, timeout=timeout, headers=headers)
                response.raise_for_status()
            except requests.RequestException as e:
                _status = getattr(getattr(e, 'response', None), 'status_code', None)
                _status_info = f" (HTTP {_status})" if _status else ""
                logging.error("API isteği başarısız oldu%s. [Detaylar gizlendi]", _status_info)
                raise APIError(f"API isteği başarısız oldu{_status_info}.") from e
            if not response.content:
                raise APIError("API'den boş veri alındı. Lütfen internet bağlantınızı kontrol edin.")
            content_type = (response.headers.get('Content-Type', '') or '').lower()
            if 'application/json' not in content_type:
                raise APIError("API, JSON formatında veri döndürmüyor. Lütfen API belgelerini kontrol edin.")
            return response
        try:
            result = retry_operation(operation, retries, backoff_factor)
        except Exception:
            self._istek_sonucunu_isle(basarili=False)
            raise
        self._istek_sonucunu_isle(basarili=True)
        self.log_message(f"{url.split('?')[0]} adresine yapılan istek başarılı. Durum: {result.status_code}")
        return result
    def _istek_sonucunu_isle(self, basarili: bool) -> None:
        with self._circuit_breaker_lock:
            if basarili:
                if self._circuit_breaker_state == "half-open":
                    logging.info("Sondaj isteği başarılı; circuit breaker kapatıldı.")
                self._failure_count = 0
                self._circuit_breaker_state = "closed"
                return
            yari_acikti = self._circuit_breaker_state == "half-open"
            self._failure_count += 1
            if yari_acikti or self._failure_count >= self._failure_threshold:
                sayac = self._failure_count
                self._failure_count = self._failure_threshold
                self._circuit_breaker_state = "open"
                self._circuit_breaker_open_until = time.monotonic() + self._circuit_breaker_reset_timeout
                if yari_acikti:
                    logging.warning(
                        "Sondaj isteği de başarısız oldu; circuit breaker %d saniye daha açık kalacak.",
                        self._circuit_breaker_reset_timeout
                    )
                else:
                    logging.warning(
                        "Arka arkaya %d başarısız istek nedeniyle circuit breaker açıldı; %d saniye boyunca API çağrıları atlanacak.",
                        sayac, self._circuit_breaker_reset_timeout
                    )

class LogBufferHandler(logging.Handler):
    def __init__(self, model: IftarModel) -> None:
        super().__init__()
        self.model = model
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = (record.levelname, self.format(record) + "\n")
        except Exception:
            self.handleError(record)
            return
        buffer = self.model.log_buffer
        try:
            buffer.put_nowait(entry)
        except queue.Full:
            try:
                buffer.get_nowait()
                buffer.put_nowait(entry)
            except (queue.Empty, queue.Full):
                pass

PRAYER_METHODS: Dict[str, str] = {
    "2": "MWL (Muslim World League)",
    "4": "Egypt (Egyptian General Authority of Survey)",
    "5": "Mekke (Umm al-Qura)",
    "7": "Tahran (Institute of Geophysics, University of Tehran)",
    "9": "Körfez Bölgesi",
    "10": "Kuveyt",
    "11": "Katar",
    "12": "ISNA (Islamic Society of North America)",
    "13": "Türkiye Diyanet",
    "15": "Jafari (Shia Ithna-Ashari, Leva Research Institute, Qum)"
}

HICRI_AY_ISIMLERI: List[str] = [
    "Muharrem", "Safer", "Rebiülevvel", "Rebiülahir",
    "Cemaziyelevvel", "Cemaziyelahir", "Recep", "Şaban",
    "Ramazan", "Şevval", "Zilkade", "Zilhicce"
]

HICRI_AY_ING_MAP: Dict[str, str] = {
    "muharram": "Muharrem",
    "safar": "Safer",
    "rabi' al-awwal": "Rebiülevvel",
    "rabi' al-thani": "Rebiülahir",
    "jumada al-awwal": "Cemaziyelevvel",
    "jumada al-thani": "Cemaziyelahir",
    "rajab": "Recep",
    "sha'ban": "Şaban",
    "ramadan": "Ramazan",
    "shawwal": "Şevval",
    "dhu al-qi'dah": "Zilkade",
    "dhu al-hijjah": "Zilhicce"
}

class IftarController:
    def __init__(self, model: IftarModel) -> None:
        self.model: IftarModel = model
        self.view: Optional["IftarView"] = None
        self._ntp_check_in_progress: bool = False
        self._ntp_check_lock = threading.Lock()
    def set_view(self, view: "IftarView") -> None:
        self.view = view
    def log_message(self, message: str) -> None:
        self.model.log_message(message)
    def clear_log(self) -> None:
        self.model.clear_log_file()
        if self.view:
            self.view.clear_console_panel()
        self.log_message("Konsol paneli temizlendi.")
    def finalize_system_check(self) -> None:
        with self._ntp_check_lock:
            if self._ntp_check_in_progress:
                return
            self._ntp_check_in_progress = True
        if self.view:
            TkManager.safe_after(0, lambda: self.view.update_sistem_saati_label("⏳", "Kontrol ediliyor...", False), context="FinalizeSystemCheck-Start")
        def check_and_update():
            try:
                result_icon, result_msg = self.model.sistem_saati_kontrol_alternative()
                if self.view:
                    TkManager.safe_after(0, lambda: self.view.update_sistem_saati_label(result_icon, result_msg), context="FinalizeSystemCheck")
                self.log_message(f"Sistem Saati Kontrolü: {result_icon} {result_msg}")
            finally:
                with self._ntp_check_lock:
                    self._ntp_check_in_progress = False
        self.model.executor.submit(check_and_update)
    def konum_guncelle(self) -> None:
        self.log_message("Otomatik konum güncelleme butonuna basıldı.")
        btn = self.view._btn_otomatik_konum if self.view else None
        self._butonu_mesgul_et(btn, "⏳ Alınıyor...")
        def task() -> None:
            try:
                yeni_konum, lat, lon = self.model.otomatik_konum_bul()
            finally:
                self._butonu_serbest_birak(btn, "🌐 Otomatik Konum Seç")
            if not yeni_konum:
                return
            self._konumu_uygula(yeni_konum, lat, lon)
            TkManager.safe_after(0, lambda: safe_showinfo("Konum Güncellendi", f"Yeni konum: {yeni_konum}"), context="KonumGuncellendiBilgi")
        self.model.executor.submit(task)
    def konum_manuel_gir(self) -> None:
        yeni_konum = safe_askstring("Manuel Konum Gir", "Konum giriniz (örn. Ankara, Turkey):")
        if not yeni_konum or not yeni_konum.strip():
            return
        yeni_konum = yeni_konum.strip()
        btn = self.view._btn_manuel_konum if self.view else None
        self._butonu_mesgul_et(btn, "⏳ Alınıyor...")
        def task() -> None:
            try:
                koordinat = self.model.konum_bilgisini_al(yeni_konum)
            finally:
                self._butonu_serbest_birak(btn, "✏️ Manuel Konum Gir")
            if not koordinat:
                if self.view:
                    self.view.show_error("Konum Hatası", f"'{yeni_konum}' konumu bulunamadı.")
                return
            self._konumu_uygula(yeni_konum, koordinat[0], koordinat[1])
        self.model.executor.submit(task)
    def _butonu_mesgul_et(self, btn: Optional[ttk.Button], metin: str) -> None:
        if btn:
            TkManager.safe_after(0, lambda: btn.config(state="disabled", text=metin), context="KonumBtnDisable")
    def _butonu_serbest_birak(self, btn: Optional[ttk.Button], metin: str) -> None:
        if btn:
            TkManager.safe_after(0, lambda: btn.config(state="normal", text=metin), context="KonumBtnRestore")
    def _konumu_uygula(self, yeni_konum: str, lat: float, lon: float) -> None:
        self.model.current_location = yeni_konum
        self.model.current_latitude, self.model.current_longitude = lat, lon
        self.model.konumu_kaydet(yeni_konum, lat, lon)
        self.log_message(f"Konum güncellendi: {yeni_konum}")
        if self.view:
            self.view.guncelle_konum_etiketi()
            self.view.verileri_yenile()
    def suanki_konum_goster(self) -> None:
        if self.view:
            def _show():
                full_location = self.model.format_active_location(self.model.current_latitude, self.model.current_longitude)
                TkManager.safe_after(0, lambda: self.view.show_info(f"Aktif Konum: {full_location}"), context="ShowCurrentLocation")
            self.model.executor.submit(_show)
    def metod_degistir(self) -> None:
        methods = PRAYER_METHODS
        method_window = tk.Toplevel(self.view.pencere)
        method_window.withdraw()
        method_window.title("Hesaplama Yöntemi Seç")
        method_window.grab_set()
        method_window.focus_force()
        method_window.transient(self.view.pencere)
        method_window.resizable(False, False)
        selected_method = tk.StringVar(value=self.model.current_method)
        ttk.Label(method_window, text="Namaz vakitlerinin hesaplanmasında kullanılacak yöntemi seçin:", wraplength=380, padding=(10, 5)).pack(anchor="w", padx=5, pady=(8, 2))
        for method_num, method_name in methods.items():
            method_label = f"({method_num}) {method_name}"
            rb = ttk.Radiobutton(method_window, text=method_label, value=method_num, variable=selected_method, style="Method.TRadiobutton")
            rb.pack(anchor='w', padx=10, pady=2)
        def apply_method():
            choice = selected_method.get()
            if choice not in methods:
                method_window.destroy()
                return
            if choice == self.model.current_method:
                method_window.destroy()
                self.view.show_info(f"Seçili yöntem zaten aktif: {methods[choice]}")
                return
            self.model.current_method = choice
            self.model.config_manager.set("metod", choice)
            self.model.config_manager.save()
            method_window.destroy()
            self.log_message(f"Hesaplama yöntemi güncellendi: {methods[choice]}")
            self.view.show_info(f"Hesaplama yöntemi güncellendi: {methods[choice]}")
            self.view.verileri_yenile()
        ttk.Separator(method_window, orient="horizontal").pack(fill="x", padx=5, pady=(6, 2))
        ttk.Button(method_window, text="Uygula", command=apply_method, style="Custom.TButton").pack(pady=5)
        def close_window(event=None):
            method_window.destroy()
        method_window.protocol("WM_DELETE_WINDOW", close_window)
        method_window.bind("<Escape>", close_window)
        method_window.bind("<Return>", lambda e: apply_method())
        self.view.alt_pencereyi_ortala(method_window)
        method_window.deiconify()
    def show_about(self) -> None:
        about_lines = []
        for mod_info in sorted(required_modules, key=lambda m: (m.pkg or m.mod_name).lower()):
            name = mod_info.pkg or mod_info.mod_name
            about_lines.append(f"{name:<25} {get_package_version(name)}")
        apiler = [
            "Namaz Vakitleri - api.aladhan.com",
            "Konum - ipinfo.io",
            "Sistem Saati - pool.ntp.org"
        ]
        about_text = f"Sürüm: {APP_VERSION}\n\nYüklü kütüphaneler ve sürümleri:\n" + "\n".join(about_lines)
        about_text += "\n\nAPI Alan Adresleri:\n" + "\n".join(apiler)
        about_text += f"\n\nÇalışma Ortamı:\nPython: {sys.version.split()[0]}\nAktif Konum: {self.model.current_location or 'Bilinmiyor'}\nHesaplama Yöntemi: ({self.model.current_method}) {PRAYER_METHODS.get(self.model.current_method, self.model.current_method)}"
        if self.view and self.view.pencere and self.view.pencere.winfo_exists():
            about_win = tk.Toplevel(self.view.pencere)
            about_win.title("Hakkında")
            about_win.transient(self.view.pencere)
            about_win.resizable(True, True)
            about_win.minsize(400, 300)
            about_win.maxsize(800, 600)
            about_win.grab_set()
            about_win.focus_force()
            txt_frame = ttk.Frame(about_win)
            txt_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))
            sb = ttk.Scrollbar(txt_frame, orient="vertical")
            sb.pack(side="right", fill="y")
            txt = tk.Text(txt_frame, font=self.view.default_font, width=60, height=22, wrap="word", bd=0, padx=8, pady=8, yscrollcommand=sb.set)
            txt.pack(side="left", fill="both", expand=True)
            sb.config(command=txt.yview)
            txt.insert("1.0", about_text)
            txt.config(state="disabled")
            ok_btn = ttk.Button(about_win, text="Tamam", command=about_win.destroy, style="Custom.TButton")
            ok_btn.pack(pady=8)
            about_win.bind("<Escape>", lambda e: about_win.destroy())
            about_win.bind("<Return>", lambda e: about_win.destroy())
            self.view.alt_pencereyi_ortala(about_win)
            ok_btn.focus_set()
        else:
            akis = getattr(self.model, "terminal_stream", None) or sys.__stdout__
            print(about_text, file=akis)
    def run(self) -> None:
        if self.view:
            self.view.run_iftar_app()

class IftarView:
    def __init__(self, controller: IftarController, model: IftarModel) -> None:
        self.controller: IftarController = controller
        self.model: IftarModel = model
        self.pencere: Optional[tk.Tk] = None
        self.ConsolePanel: Optional[tk.Text] = None
        self.sistem_saati_label: Optional[tk.Label] = None
        self.default_font: Optional[tkFont.Font] = None
        self.bold_font: Optional[tkFont.Font] = None
        self.large_bold_font: Optional[tkFont.Font] = None
        self.vakit_cerceve: Optional[tk.Frame] = None
        self.windowed_geometry: Optional[str] = None
        self.static_prefix = "📍 Aktif Konum: "
        self.dynamic_entry: Optional[tk.Entry] = None
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.tooltip_after_id: Optional[str] = None
        self._kopyala_menu: Optional[tk.Menu] = None
        self._last_configure_time: float = 0
        self._tooltip_seq: int = 0
        self.aktif_konum_static_label: Optional[tk.Widget] = None
        self.sayac_label: Optional[tk.Label] = None
        self.yuzde_cubugu: Optional[ttk.Progressbar] = None
        self.yuzde_etiket: Optional[tk.Label] = None
        self.prayer_labels: Optional[List[tk.Widget]] = None
        self.prayer_time_labels: Optional[List[tk.Widget]] = None
        self.check_module_updates_var = None
        self._last_vakit_indices = None
        self._last_countdown_date: Optional[object] = None
        self._progressbar_mode: Optional[str] = None
        self._last_arayuz_minute: Any = (-1, -1)
        self._iftar_celebrated_date: Optional[object] = None
        self._time_parse_cache: Dict[str, Any] = {}
        self._pl_state: List[Any] = [None] * 6
        self._pl_time_state: List[Any] = [None] * 6
        self._vakitler: tuple = ("İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı")
        self._vakitler_ing: tuple = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
        self._last_saatler: Optional[tuple] = None
        self._tp_key: Optional[Any] = None
        self._tp_values: Optional[tuple] = None
        self.console_frame: Optional[ttk.Frame] = None
        self._konum_fetch_in_progress: bool = False
        self._konum_fetch_bekliyor: bool = False
        self._konum_fetch_lock = threading.Lock()
        self._yenileme_calisiyor: bool = False
        self._yenileme_bekliyor: bool = False
        self._yenileme_lock = threading.Lock()
        self._api_check_lock = threading.Lock()
        self._countdown_parsed_key: Optional[tuple] = None
        self._countdown_parsed_times: Optional[tuple] = None
        self._last_imsakiye_hash: Optional[int] = None
        self._imsakiye_anahtari: Optional[tuple] = None
        self.imsak_tree: Optional[ttk.Treeview] = None
        self.style: Optional[ttk.Style] = None
        self._compare_button: Optional[ttk.Button] = None
        self._btn_otomatik_konum: Optional[ttk.Button] = None
        self._btn_manuel_konum: Optional[ttk.Button] = None
        self._startup_retry_btn: Optional[ttk.Button] = None
        self._api_status_label: Optional[ttk.Label] = None
        self._api_check_busy: bool = False
        self._api_check_after_id: Optional[str] = None
        self._imsakiye_baslik: Optional[tk.Entry] = None
        self._dosya_adi: str = ""
        self.developer_mode_var: Optional[tk.BooleanVar] = None
        self._countdown_after_id: Optional[str] = None
        self._otomatik_yenileme_id: Optional[str] = None
        self._label_texts: tuple = tuple(
            f"{self._vakitler[i]} ({self._vakitler_ing[i]}) {self.model.emojiler[i]}" for i in range(6)
        )
    def _asgari_yukseklik(self) -> int:
        return WIN_HEIGHT_DEV if self.model.DEVELOPER_MODE else WIN_HEIGHT_NORMAL
    def toggle_module_update_check(self) -> None:
        new_val = self.check_module_updates_var.get()
        self.model.config_manager.set("check_module_updates", "True" if new_val else "False")
        self.model.config_manager.save()
        self.controller.log_message(f"Açılışta modül güncellemeleri kontrol et: {'Aktif' if new_val else 'Pasif'}")
    def toggle_developer_mode(self) -> None:
        new_val = self.developer_mode_var.get()
        self.model.DEVELOPER_MODE = new_val
        self.model.config_manager.set("DEVELOPER_MODE", "True" if new_val else "False")
        self.model.config_manager.save()
        if self.console_frame:
            if new_val:
                self.console_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
                self.update_console_from_model()
            else:
                self.console_frame.pack_forget()
        try:
            if self.pencere and self.pencere.winfo_exists() and not self.pencere.attributes("-fullscreen"):
                geom = self.pencere.geometry()
                geom_match = GEOMETRY_RE.match(geom)
                if geom_match:
                    self.pencere.geometry(f"{geom_match.group(1)}x{self._asgari_yukseklik()}+{geom_match.group(3)}+{geom_match.group(4)}")
        except Exception as e:
            logging.debug("Pencere geometrisi güncellenirken hata: %s", e)
        self.controller.log_message(f"Geliştirici Modu {'aktif' if new_val else 'pasif'} olarak güncellendi.")
    def guncelle_konum_etiketi(self) -> None:
        with self._konum_fetch_lock:
            if self._konum_fetch_in_progress:
                self._konum_fetch_bekliyor = True
                return
            self._konum_fetch_in_progress = True
        def heavy_task():
            try:
                TkManager.safe_after(0, lambda: self._update_dynamic_entry("⏳ Güncelleniyor..."), context="KonumLoading")
                city = ""
                ulke_kodu = ""
                lat = self.model.current_latitude
                lon = self.model.current_longitude
                if lat is not None and lon is not None:
                    location = self.model.konum_nesnesi_al(lat, lon, language="en")
                    if location:
                        address_details = location.raw.get("address", {})
                        city = (address_details.get("city") or address_details.get("state") or
                                address_details.get("town") or address_details.get("village") or
                                address_details.get("municipality") or address_details.get("county") or "").strip()
                        ulke_kodu = address_details.get("country_code", "")
                        if not city and location.address:
                            city = location.address.split(",")[0].strip()
                    active_text = f"{city} {ulke_bayragi(ulke_kodu)}: {lat:.2f}° , {lon:.2f}°"
                else:
                    active_text = "Konum bilgisi yok"
                TkManager.safe_after(0, lambda: self._update_dynamic_entry(active_text), context="KonumEtiketi")
            finally:
                with self._konum_fetch_lock:
                    self._konum_fetch_in_progress = False
                    tekrar = self._konum_fetch_bekliyor
                    self._konum_fetch_bekliyor = False
                if tekrar:
                    self.guncelle_konum_etiketi()
        self.model.executor.submit(heavy_task)
    def toggle_fullscreen(self, event: tk.Event = None) -> str:
        is_fullscreen = self.pencere.attributes("-fullscreen")
        if not is_fullscreen:
            self.windowed_geometry = self.pencere.geometry()
            self.pencere.attributes("-fullscreen", True)
        else:
            self.pencere.attributes("-fullscreen", False)
            if self.windowed_geometry:
                self.pencere.geometry(self.windowed_geometry)
        return "break"
    def _update_dynamic_entry(self, text: str) -> None:
        if self.dynamic_entry:
            clean_text = text.strip()
            if clean_text == "Konum bilgisi yok":
                if self.aktif_konum_static_label:
                    self.aktif_konum_static_label.config(text="❌ Konum alınamadı.")
                self.dynamic_entry.grid_remove()
                return
            if self.aktif_konum_static_label:
                self.aktif_konum_static_label.config(text=self.static_prefix)
            self.dynamic_entry.grid()
            self.dynamic_entry.config(state="normal")
            self.dynamic_entry.delete(0, "end")
            self.dynamic_entry.insert(0, clean_text)
            self.dynamic_entry.config(state="readonly")
    def kopyala_menusu(self, event: tk.Event) -> str:
        widget = event.widget
        if self._kopyala_menu is None:
            self._kopyala_menu = tk.Menu(self.pencere, tearoff=0)
            self._kopyala_menu.add_command(label="Kopyala")
        durum = "normal" if self._kopyalanacak_metin(widget) else "disabled"
        self._kopyala_menu.entryconfigure(0, state=durum, command=lambda: self.copy_text_from_widget(widget))
        self._kopyala_menu.tk_popup(event.x_root, event.y_root)
        self._kopyala_menu.grab_release()
        return "break"

    def _kopyalanacak_metin(self, widget: tk.Widget) -> str:
        try:
            if isinstance(widget, (tk.Label, ttk.Label)):
                return widget.cget("text")
            if isinstance(widget, tk.Entry):
                return widget.selection_get() if widget.selection_present() else widget.get()
            return widget.selection_get()
        except tk.TclError:
            return ""

    def copy_text_from_widget(self, widget: tk.Widget) -> None:
        metin = self._kopyalanacak_metin(widget)
        if not metin:
            return
        try:
            self.pencere.clipboard_clear()
            self.pencere.clipboard_append(metin)
        except tk.TclError as e:
            logging.error("Panoya kopyalanamadı: %s", e)
            safe_showerror("Kopyalama Hatası", f"Panoya kopyalarken hata oluştu:\n{e}")

    def show_full_location_tooltip(self, event: tk.Event) -> None:
        x_root, y_root = event.x_root, event.y_root
        istek_no = self._tooltip_seq

        def _display_tooltip_with_text(full_text: str, x: int, y: int):
            if istek_no != self._tooltip_seq: return
            if not (self.pencere and self.pencere.winfo_exists()): return
            if self.tooltip_window and self.tooltip_window.winfo_exists():
                try:
                    self.tooltip_window.destroy()
                except tk.TclError:
                    pass
            self.tooltip_window = None
            try:
                self.tooltip_window = tk.Toplevel(self.pencere)
                self.tooltip_window.overrideredirect(True)
                font_to_use = self.default_font if hasattr(self, 'default_font') else None
                label = ttk.Label(self.tooltip_window, text=full_text, background="#FFFFE0", relief="solid", borderwidth=1, font=font_to_use, padding=(3, 1))
                label.pack()
                self.tooltip_window.update_idletasks()
                tooltip_width = self.tooltip_window.winfo_reqwidth()
                tooltip_height = self.tooltip_window.winfo_reqheight()
                screen_width = self.pencere.winfo_screenwidth()
                screen_height = self.pencere.winfo_screenheight()
                final_x = x + 15
                final_y = y + 10
                if final_x + tooltip_width > screen_width:
                    final_x = x - tooltip_width - 5
                if final_y + tooltip_height > screen_height:
                    final_y = y - tooltip_height - 5
                if final_x < 0: final_x = 0
                if final_y < 0: final_y = 0

                self.tooltip_window.geometry(f"+{final_x}+{final_y}")

            except Exception as e_create:
                logging.error(f"Tooltip oluşturulurken hata: {e_create}", exc_info=True)
                if self.tooltip_window and self.tooltip_window.winfo_exists():
                    try:
                        self.tooltip_window.destroy()
                    except tk.TclError:
                        pass
                self.tooltip_window = None

        lat = self.model.current_latitude
        lon = self.model.current_longitude
        if lat is None or lon is None:
            _display_tooltip_with_text("Konum bilgisi yok", x_root, y_root)
            return

        def fetch_and_display():
            adres = self.model.format_active_location(lat, lon)
            TkManager.safe_after(0, lambda: _display_tooltip_with_text(adres, x_root, y_root), context="TooltipGoster")
        self.model.executor.submit(fetch_and_display)

    def hide_tooltip(self, event: Optional[tk.Event] = None) -> None:
        if self.tooltip_window and self.tooltip_window.winfo_exists():
            self.tooltip_window.destroy()
        self.tooltip_window = None
    def schedule_tooltip(self, event: tk.Event) -> None:
        self.cancel_tooltip()
        if self.pencere and self.pencere.winfo_exists():
            self.tooltip_after_id = self.pencere.after(500, lambda ev=event: self.show_full_location_tooltip(ev))

    def cancel_tooltip(self, event: Optional[tk.Event] = None) -> None:
        self._tooltip_seq += 1
        if self.tooltip_after_id:
            try:
                if self.pencere and self.pencere.winfo_exists():
                    self.pencere.after_cancel(self.tooltip_after_id)
            except tk.TclError as e_cancel:
                logging.debug("cancel_tooltip: after_cancel başarısız (%s): %s", self.tooltip_after_id, e_cancel)
            finally:
                self.tooltip_after_id = None
        self.hide_tooltip(event)
    @run_on_main_thread
    def guncelle_takvim(self, imsakiye: List[List[str]], anahtar: tuple) -> None:
        if self.imsak_tree is None:
            return
        if self._imsakiye_anahtari != anahtar:
            self._imsakiye_anahtari = anahtar
            self._last_imsakiye_hash = None
            for item in self.imsak_tree.get_children():
                self.imsak_tree.delete(item)
        if not imsakiye:
            return
        _new_hash = hash(tuple(tuple(row) for row in imsakiye))
        if self._last_imsakiye_hash == _new_hash and self.imsak_tree.get_children():
            return
        self._last_imsakiye_hash = _new_hash
        for item in self.imsak_tree.get_children():
            self.imsak_tree.delete(item)
        today_fmt = babel_dates.format_date(self.model.yerel_simdi().date(), "d MMMM yyyy EEEE", locale='tr_TR')
        today_iid = None
        for row in imsakiye:
            iid = self.imsak_tree.insert("", "end", values=row)
            if row[0] == today_fmt:
                self.imsak_tree.item(iid, tags=("today",))
                today_iid = iid
        if today_iid:
            self.imsak_tree.see(today_iid)
        elif self.imsak_tree.get_children():
            self.imsak_tree.see(self.imsak_tree.get_children()[0])
        logging.info("İmsak takvimi güncellendi.")
    def _sayaci_durdur(self) -> None:
        if self._countdown_after_id is None:
            return
        try:
            if self.pencere and self.pencere.winfo_exists():
                self.pencere.after_cancel(self._countdown_after_id)
        except tk.TclError as e:
            logging.debug("Sayaç zamanlayıcısı iptal edilemedi: %s", e)
        self._countdown_after_id = None
    def update_countdown(self) -> None:
        self._sayaci_durdur()
        if not self.model.current_ezan_saatleri:
            if self._progressbar_mode != "loading":
                self._progressbar_mode = "loading"
                self.yuzde_cubugu.config(mode="indeterminate", style="TProgressbar")
                self.yuzde_cubugu.start(50)
            self._countdown_after_id = TkManager.safe_after(100, self.update_countdown, context="UpdateCountdown-StartWait")
            return
        if self._progressbar_mode == "loading":
            self.yuzde_cubugu.stop()
            self.yuzde_cubugu.config(mode="determinate")
            self._progressbar_mode = None
        tz_str = self.model.current_ezan_saatleri.get("timezone")
        tz = self.model.zaman_dilimi()
        now = get_utc_now().astimezone(tz)
        _last_date = self._last_countdown_date
        if _last_date is not None and _last_date != now.date():
            self.model.yesterday_maghrib_str = self.model.current_ezan_saatleri.get("maghrib", "")
            self.model.tomorrow_imsak_str = None
            self.verileri_yenile()
        self._last_countdown_date = now.date()
        imsak_str = self.model.current_ezan_saatleri.get("fajr", "06:00")
        iftar_str = self.model.current_ezan_saatleri.get("maghrib", "20:00")
        _parse_key = (now.date(), imsak_str, iftar_str, tz_str)
        if self._countdown_parsed_key == _parse_key and self._countdown_parsed_times is not None:
            imsak_time, iftar_time = self._countdown_parsed_times
        else:
            try:
                imsak_time = datetime.combine(now.date(), datetime.strptime(imsak_str, "%H:%M").time(), tzinfo=tz)
                iftar_time = datetime.combine(now.date(), datetime.strptime(iftar_str, "%H:%M").time(), tzinfo=tz)
            except ValueError as ve:
                self.controller.log_message(f"Zaman formatı hatası: {ve}. Varsayılan saatler kullanılacak.")
                imsak_time = datetime.combine(now.date(), datetime.strptime("06:00", "%H:%M").time(), tzinfo=tz)
                iftar_time = datetime.combine(now.date(), datetime.strptime("20:00", "%H:%M").time(), tzinfo=tz)
            self._countdown_parsed_key = _parse_key
            self._countdown_parsed_times = (imsak_time, iftar_time)
        if now < imsak_time:
            kalan_str = sure_hms((imsak_time - now).total_seconds())
            _ym = self.model.yesterday_maghrib_str
            try:
                bir_onceki = datetime.combine(now.date() - timedelta(days=1), datetime.strptime(_ym, "%H:%M").time(), tzinfo=tz) if _ym else iftar_time - timedelta(days=1)
            except ValueError:
                bir_onceki = iftar_time - timedelta(days=1)
            toplam = (imsak_time - bir_onceki).total_seconds()
            yuzde = ilerleme_yuzdesi((now - bir_onceki).total_seconds(), toplam)
            self.sayac_label.config(text=f"İmsak Öncesi, Sahura Kalan: {kalan_str} ({imsak_str})", foreground="#C87000")
            self.yuzde_etiket.config(text=f"Serbest yeme içme süresi: {sure_hm(toplam)}, %{yuzde:.1f} tamamlandı".replace('.', ','), foreground="#C87000")
            self.yuzde_cubugu["value"] = yuzde
            if self._progressbar_mode != "free":
                self._progressbar_mode = "free"
                self.yuzde_cubugu.config(style="Free.Horizontal.TProgressbar")
        elif now < iftar_time:
            kalan_str = sure_hms((iftar_time - now).total_seconds())
            toplam = (iftar_time - imsak_time).total_seconds()
            yuzde = ilerleme_yuzdesi((now - imsak_time).total_seconds(), toplam)
            self.sayac_label.config(text=f"Oruç, İftara Kalan: {kalan_str} ({iftar_str})", foreground="#2E8B57")
            self.yuzde_etiket.config(text=f"Oruç süresi: {sure_hm(toplam)}, %{yuzde:.1f} tamamlandı".replace('.', ','), foreground="#2E8B57")
            self.yuzde_cubugu["value"] = yuzde
            if self._progressbar_mode != "fasting":
                self._progressbar_mode = "fasting"
                self.yuzde_cubugu.config(style="Fasting.Horizontal.TProgressbar")
        else:
            if self._iftar_celebrated_date != now.date() and (now - iftar_time).total_seconds() < 60:
                self._iftar_celebrated_date = now.date()
                self.sayac_label.config(text="🎉 İftar vakti!", foreground="#27AE60")
                self.yuzde_etiket.config(text="Hayırlı iftarlar 🍽️", foreground="#27AE60")
                self.yuzde_cubugu["value"] = 100
                if self._progressbar_mode != "celebration":
                    self._progressbar_mode = "celebration"
                    self.yuzde_cubugu.config(style="Celebration.Horizontal.TProgressbar")
                self._countdown_after_id = TkManager.safe_after(30000, self.update_countdown, context="IftarCelebration")
                return
            _ti = self.model.tomorrow_imsak_str
            try:
                next_imsak = datetime.combine(now.date() + timedelta(days=1), datetime.strptime(_ti, "%H:%M").time(), tzinfo=tz) if _ti else imsak_time + timedelta(days=1)
            except ValueError:
                next_imsak = imsak_time + timedelta(days=1)
            kalan_str = sure_hms((next_imsak - now).total_seconds())
            toplam = (next_imsak - iftar_time).total_seconds()
            yuzde = ilerleme_yuzdesi((now - iftar_time).total_seconds(), toplam)
            self.sayac_label.config(text=f"🎉 İftar Sonrası, Sahura Kalan: {kalan_str} ({_ti or '-'})", foreground="#27AE60")
            self.yuzde_etiket.config(text=f"Hayırlı iftarlar 🍽️  |  Serbest: {sure_hm(toplam)}, %{yuzde:.1f} tamamlandı".replace('.', ','), foreground="#27AE60")
            self.yuzde_cubugu["value"] = yuzde
            if self._progressbar_mode != "post_iftar":
                self._progressbar_mode = "post_iftar"
                self.yuzde_cubugu.config(style="Celebration.Horizontal.TProgressbar")
        if self.model.current_ezan_saatleri and (now.hour, now.minute) != self._last_arayuz_minute:
            if not (self.pencere and self.pencere.winfo_exists() and self.pencere.state() == "iconic"):
                self._last_arayuz_minute = (now.hour, now.minute)
                self.arayuzu_guncelle(self.model.current_ezan_saatleri)
        delay = 5000 if (self.pencere and self.pencere.winfo_exists() and self.pencere.state() == "iconic") else 1000
        self._countdown_after_id = TkManager.safe_after(delay, self.update_countdown, context="UpdateCountdown-Tick")
    def verileri_yenile(self) -> None:
        with self._yenileme_lock:
            if self._yenileme_calisiyor:
                self._yenileme_bekliyor = True
                return
            self._yenileme_calisiyor = True
        threading.Thread(target=self._yenileme_gorevi, daemon=True, name="veri-yenileme").start()
    @staticmethod
    def _future_sonucu(future: "concurrent.futures.Future", etiket: str, timeout: int = 90) -> Any:
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logging.warning("%s isteği %d saniyede tamamlanamadı.", etiket, timeout)
        except Exception as e:
            logging.warning("%s isteği başarısız: %s", etiket, e)
        return None
    def _yenileme_gorevi(self) -> None:
        try:
            enlem, boylam = self.model.aktif_koordinatlar()
            method = self.model.current_method
            bugun = self.model.yerel_simdi()
            dun = (bugun - timedelta(days=1)).strftime('%d-%m-%Y')
            yarin = (bugun + timedelta(days=1)).strftime('%d-%m-%Y')
            f_bugun = self.model.executor.submit(self.model.ezan_saatlerini_hesapla, enlem, boylam, method)
            f_dun = self.model.executor.submit(self.model.ezan_saatlerini_hesapla, enlem, boylam, method, dun)
            f_yarin = self.model.executor.submit(self.model.ezan_saatlerini_hesapla, enlem, boylam, method, yarin)
            ezan_saatleri = self._future_sonucu(f_bugun, "Bugünün namaz vakitleri")
            anahtar = (bugun.date(), enlem, boylam, method)
            if ezan_saatleri:
                self.model.current_ezan_saatleri = ezan_saatleri
                self.model.current_ezan_anahtari = anahtar
                if self.model.yerel_simdi().date() != bugun.date():
                    logging.info("Konumun yerel tarihi sistem tarihinden farklı; vakitler doğru tarih için yeniden alınacak.")
                    self.verileri_yenile()
            elif self.model.current_ezan_anahtari != anahtar:
                self.model.current_ezan_saatleri = {}
            dun_ezan = self._future_sonucu(f_dun, "Dünün namaz vakitleri")
            if dun_ezan:
                self.model.yesterday_maghrib_str = dun_ezan.get("maghrib", "")
            yarin_ezan = self._future_sonucu(f_yarin, "Yarının namaz vakitleri")
            if yarin_ezan:
                self.model.tomorrow_imsak_str = yarin_ezan.get("fajr", "")
            self.arayuzu_guncelle(self.model.current_ezan_saatleri)
            TkManager.safe_after(0, self._yenileme_sonucunu_isle, context="EzanYenilemeSonucu")
            self._hicri_basligi_getir()
            self.guncelle_takvim(self.model.imsakiye_takvimini_al(), (enlem, boylam, method))
        except Exception as e:
            logging.error("Veri yenileme görevi beklenmedik şekilde sonlandı: %s", e, exc_info=True)
            TkManager.safe_after(0, self._yenileme_sonucunu_isle, context="EzanYenilemeHata")
        finally:
            with self._yenileme_lock:
                self._yenileme_calisiyor = False
                tekrar = self._yenileme_bekliyor
                self._yenileme_bekliyor = False
            if tekrar:
                self.verileri_yenile()
    @run_on_main_thread
    def run_iftar_app(self) -> None:
        self._pencereyi_hazirla()
        self._menuyu_olustur()
        self._ust_paneli_olustur()
        self._vakit_panelini_olustur()
        self._sayac_panelini_olustur()
        self._takvim_panelini_olustur()
        self._konsol_panelini_olustur()
        self._kapanisi_baglat()
        self.verileri_yenile()
        TkManager.safe_after(500, self._konsolu_periyodik_guncelle, context="InitialConsoleUpdate")
        self.pencere.deiconify()
        self.pencere.mainloop()
    def _pencereyi_hazirla(self) -> None:
        if TkManager.main_instance is None:
            self.pencere = tk.Tk()
            TkManager.main_instance = self.pencere
            logging.info("Ana Tkinter penceresi oluşturuldu.")
        else:
            self.pencere = TkManager.main_instance
            logging.warning("Mevcut ana Tkinter penceresi yeniden kullanılıyor.")
        self.pencere.after(100, TkManager.process_callback_queue)
        self.pencere.report_callback_exception = self._tk_hatasini_bildir
        self.pencere.withdraw()
        self.patch_messagebox_functions()
        self._dosya_adi = os.path.basename(sys.executable if getattr(sys, "frozen", False) else __file__)
        pencere_boyutu = self.get_window_geometry()
        geom_match = GEOMETRY_RE.match(pencere_boyutu)
        if geom_match:
            yukseklik = max(int(geom_match.group(2)), self._asgari_yukseklik())
            pencere_boyutu = f"{geom_match.group(1)}x{yukseklik}+{geom_match.group(3)}+{geom_match.group(4)}"
        self.windowed_geometry = pencere_boyutu
        self.pencere.title(f"Namaz Vakitleri - {self._dosya_adi}")
        self.pencere.geometry(pencere_boyutu)
        self.pencere.minsize(650, 400)
        self.pencere.update_idletasks()
        self.create_fonts(self.pencere)
        self._stilleri_ayarla()
        self.pencere.bind("<F11>", self.toggle_fullscreen)
        self.pencere.bind("<Escape>", lambda e: self.toggle_fullscreen(e) if self.pencere.attributes("-fullscreen") else None)
        self.pencere.bind("<Configure>", self.on_configure)
        self.pencere.bind("<Map>", self._pencere_goruntulendi)
        TkManager.safe_after(100, self.controller.finalize_system_check, context="FinalizeSystemCheck")
    def _pencere_goruntulendi(self, event: tk.Event) -> None:
        if event.widget is self.pencere:
            TkManager.safe_after(0, self.update_countdown, context="WindowRestore")
    def _tk_hatasini_bildir(self, exc, val, tb) -> None:
        hata_metni = "".join(traceback.format_exception(exc, val, tb))
        logging.error("Tkinter hatası: %s", hata_metni)
        safe_showerror("Hata", f"Beklenmeyen bir Tkinter hatası oluştu. Lütfen log dosyasını kontrol ediniz.\n\nHata Detayları:\n{hata_metni}")
    def _stilleri_ayarla(self) -> None:
        self.style = ttk.Style()
        self.style.configure("Custom.TButton", font=("Segoe UI Emoji", 9))
        self.style.configure("Method.TRadiobutton", font=("Segoe UI Emoji", 10))
        self.style.configure("Treeview.Heading", font=("Segoe UI Emoji", 10, "bold"))
        self.style.configure("Treeview", rowheight=24)
        self.style.configure("TLabelframe.Label", font=self.bold_font)
        self.style.configure("Fasting.Horizontal.TProgressbar", troughcolor="#D0E8D0", background="#2E8B57", thickness=22)
        self.style.configure("Free.Horizontal.TProgressbar", troughcolor="#F5E0C0", background="#D4A020", thickness=22)
        self.style.configure("Celebration.Horizontal.TProgressbar", troughcolor="#E8F5E8", background="#27AE60", thickness=22)
        self.style.map("Treeview", background=[("selected", "#6CC08A")], foreground=[("selected", "#1A1A1A")])
    def _menuyu_olustur(self) -> None:
        self.check_module_updates_var = tk.BooleanVar(master=self.pencere)
        self.check_module_updates_var.set(parse_bool(self.model.config_manager.get("check_module_updates", "False")))
        self.developer_mode_var = tk.BooleanVar(master=self.pencere)
        self.developer_mode_var.set(parse_bool(self.model.config_manager.get("DEVELOPER_MODE", "False")))
        menubar = tk.Menu(self.pencere)
        self.pencere.config(menu=menubar)
        top_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Menü", menu=top_menu)
        top_menu.add_command(label="Hakkında", command=self.controller.show_about)
        top_menu.add_checkbutton(label="Açılışta Modül Güncellemelerini Kontrol Et",
                                 variable=self.check_module_updates_var,
                                 command=self.toggle_module_update_check)
        top_menu.add_checkbutton(label="Geliştirici Modu",
                                 variable=self.developer_mode_var,
                                 command=self.toggle_developer_mode)
    def _ust_paneli_olustur(self) -> None:
        ust_frame = ttk.Frame(self.pencere)
        ust_frame.pack(side="top", fill="x", padx=10, pady=10)
        ust_frame.columnconfigure(0, weight=0, minsize=360)
        ust_frame.columnconfigure(1, weight=1, minsize=200)
        ust_frame.columnconfigure(2, weight=0, minsize=330)
        ust_frame.rowconfigure(0, minsize=150)
        self._ayarlar_kutusunu_olustur(ust_frame)
        baslik_frame = ttk.Frame(ust_frame)
        baslik_frame.grid(row=0, column=1, padx=10, pady=5)
        self.baslik_label = ttk.Label(baslik_frame, text="🕌 Namaz Vakitleri", font=self.large_bold_font, foreground="#1A6CA8")
        self.baslik_label.pack()
        self._saglik_kutusunu_olustur(ust_frame)
    def _ayarlar_kutusunu_olustur(self, ust_frame: ttk.Frame) -> None:
        ayarlar_frame = ttk.Labelframe(ust_frame, text="Ayarlar", labelanchor="n", padding=10, width=360, height=150)
        ayarlar_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        ayarlar_frame.grid_propagate(False)
        ayarlar_frame.columnconfigure(0, weight=1)
        ayarlar_frame.columnconfigure(1, weight=1)
        self._btn_otomatik_konum = self.create_logged_button(ayarlar_frame, text="🌐 Otomatik Konum Seç", command=self.controller.konum_guncelle)
        self._btn_otomatik_konum.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        btn_suanki_konum = self.create_logged_button(ayarlar_frame, text="📌 Aktif Konumu Göster", command=self.controller.suanki_konum_goster)
        btn_suanki_konum.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        btn_metod_degistir = self.create_logged_button(ayarlar_frame, text="⚙️ Yöntem Değiştir", command=self.controller.metod_degistir)
        btn_metod_degistir.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        self._btn_manuel_konum = self.create_logged_button(ayarlar_frame, text="✏️ Manuel Konum Gir", command=self.controller.konum_manuel_gir)
        self._btn_manuel_konum.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    def _saglik_kutusunu_olustur(self, ust_frame: ttk.Frame) -> None:
        sag_frame = ttk.Labelframe(ust_frame, text="Uygulama Sağlığı", labelanchor="n", padding=10, width=330, height=150)
        sag_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        sag_frame.grid_propagate(False)
        sag_frame.columnconfigure(0, weight=1)
        sag_frame.rowconfigure(0, weight=1)
        center_container = ttk.Frame(sag_frame)
        center_container.grid(row=0, column=0)
        self._api_status_label = ttk.Label(center_container, text="⏳ API Durumu: Kontrol ediliyor...", font=self.default_font, anchor="w", justify="left", foreground="#888888")
        self._api_status_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self._api_status_label.bind("<Button-1>", lambda _e: self.model.executor.submit(self._api_durumunu_kontrol_et))
        self.model.executor.submit(self._api_durumunu_kontrol_et)
        system_frame = ttk.Frame(center_container)
        system_frame.grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.sistem_saati_label = ttk.Label(system_frame, text="⏳ Sistem Saati Kontrolü: Kontrol ediliyor...", font=self.default_font, anchor="w", justify="left")
        self.sistem_saati_label.grid(row=0, column=0, sticky="w")
        self._compare_button = self.create_logged_button(system_frame, text="🔄 Karşılaştır", command=self.controller.finalize_system_check)
        self._compare_button.grid(row=0, column=1, sticky="w", padx=(5, 0))
        aktif_konum_frame = ttk.Frame(center_container)
        aktif_konum_frame.grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.aktif_konum_static_label = ttk.Label(aktif_konum_frame, text=self.static_prefix if self.model.current_location else "❌ Konum alınamadı.", font=self.default_font, anchor="w", justify="left")
        self.aktif_konum_static_label.grid(row=0, column=0, sticky="w")
        arka_plan = self.style.lookup("TFrame", "background")
        self.dynamic_entry = tk.Entry(aktif_konum_frame, width=29, font=self.default_font, bd=0, relief="flat", exportselection=1, cursor="arrow", readonlybackground=arka_plan)
        self.dynamic_entry.grid(row=0, column=1, sticky="w", padx=(2, 0))
        self.dynamic_entry.bind("<Map>", lambda e: e.widget.config(readonlybackground=self.style.lookup("TFrame", "background")))
        self.dynamic_entry.bind("<Enter>", self.schedule_tooltip)
        self.dynamic_entry.bind("<Leave>", self.cancel_tooltip)
        self.dynamic_entry.bind("<Button-3>", self.kopyala_menusu)
        self.dynamic_entry.bind("<Control-c>", lambda event: self.copy_text_from_widget(self.dynamic_entry))
        self.guncelle_konum_etiketi()
    def _api_durumunu_kontrol_et(self) -> None:
        with self._api_check_lock:
            if self._api_check_busy:
                return
            self._api_check_busy = True
        try:
            TkManager.safe_after(0, lambda: self._api_status_label.config(text="⏳ API Durumu: Kontrol ediliyor...", foreground="#888888"), context="ApiCheckLoading")
            domain, ping_ms = self.model.api_saglik_durumu()
        except Exception as e:
            logging.warning("API durum kontrolü sırasında beklenmedik hata: %s", e)
            domain, ping_ms = ("api.aladhan.com", "bağlantı kurulamadı")
        if isinstance(ping_ms, int):
            metin = f"{'✅' if ping_ms < 500 else '⚠️'} API Durumu ({domain}): {ping_ms} ms"
            renk = "#007040" if ping_ms < 500 else "#C87000"
            sonraki_ms = 300000
        else:
            metin = f"❌ API Durumu ({domain}): {ping_ms}"
            renk = "#CC2222"
            sonraki_ms = 60000
        def _guncelle_ve_yeniden_planla():
            with self._api_check_lock:
                self._api_check_busy = False
            self._api_status_label.config(text=metin, foreground=renk)
            if self._api_check_after_id is not None:
                try:
                    self.pencere.after_cancel(self._api_check_after_id)
                except tk.TclError as e:
                    logging.debug("API kontrol zamanlayıcısı iptal edilemedi: %s", e)
            self._api_check_after_id = TkManager.safe_after(sonraki_ms, lambda: self.model.executor.submit(self._api_durumunu_kontrol_et), context="PeriodicApiCheck")
        TkManager.safe_after(0, _guncelle_ve_yeniden_planla, context="CheckApiStatus")
    def _vakit_panelini_olustur(self) -> None:
        self.vakit_cerceve = ttk.Labelframe(self.pencere, text="Namaz Vakitleri", labelanchor="n", padding=5)
        self.vakit_cerceve.pack(pady=10, padx=10, fill="x", expand=True)
        self.model.current_ezan_saatleri = {}
        self.arayuzu_guncelle({})
    def _yenileme_sonucunu_isle(self) -> None:
        if self.model.current_ezan_saatleri:
            if self._startup_retry_btn and self._startup_retry_btn.winfo_exists():
                self._startup_retry_btn.destroy()
                self._startup_retry_btn = None
            self.update_countdown()
            return
        self._sayaci_durdur()
        self.sayac_label.config(text="❌ Namaz vakitleri alınamadı, bağlantınızı kontrol edin", foreground="#CC2222")
        self.yuzde_cubugu.stop()
        self.yuzde_cubugu.config(mode="determinate", value=0)
        self._progressbar_mode = None
        if self._otomatik_yenileme_id is None:
            self._otomatik_yenileme_id = TkManager.safe_after(60000, self._otomatik_yeniden_dene, context="OtomatikYenidenDeneme")
        if self._startup_retry_btn and self._startup_retry_btn.winfo_exists():
            return
        def _tekrar_dene():
            self._startup_retry_btn.destroy()
            self._startup_retry_btn = None
            self.sayac_label.config(text="⏳ Yükleniyor...", foreground="")
            self.verileri_yenile()
            self.update_countdown()
        self._startup_retry_btn = self.create_logged_button(self.yuzde_cubugu.master, text="🔄 Tekrar Dene", command=_tekrar_dene)
        self._startup_retry_btn.grid(row=3, column=0, padx=5, pady=(2, 5))
    def _otomatik_yeniden_dene(self) -> None:
        self._otomatik_yenileme_id = None
        if not self.model.current_ezan_saatleri:
            self.controller.log_message("Namaz vakitleri alınamamıştı; otomatik olarak yeniden deneniyor.")
            self.verileri_yenile()
    def _sayac_panelini_olustur(self) -> None:
        cerceve = ttk.Labelframe(self.pencere, text="İftar Sayacı", labelanchor="n", padding=5)
        cerceve.pack(pady=10, padx=10, fill="x")
        cerceve.columnconfigure(0, weight=1)
        self.sayac_label = ttk.Label(cerceve, text="⏳ Yükleniyor...", font=self.large_bold_font, anchor="center", justify="center")
        self.sayac_label.grid(row=0, column=0, padx=2, pady=5, sticky="ew")
        self.yuzde_cubugu = ttk.Progressbar(cerceve, orient="horizontal", mode="determinate")
        self.yuzde_cubugu.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.yuzde_etiket = ttk.Label(cerceve, text="", font=self.default_font, anchor="center", justify="center")
        self.yuzde_etiket.grid(row=2, column=0, padx=5, pady=5)
        self.update_countdown()
    def _takvim_panelini_olustur(self) -> None:
        imsak_frame = ttk.Frame(self.pencere)
        imsak_frame.pack(fill="x", padx=10, pady=(0, 10))
        self._imsakiye_baslik = tk.Entry(imsak_frame, font=self.large_bold_font, justify="center", bd=0, relief="flat", exportselection=1, readonlybackground=self.style.lookup("TFrame", "background"))
        self._imsakiye_baslik.insert(0, "⏳ Yükleniyor...")
        self._imsakiye_baslik.config(state="readonly")
        self._imsakiye_baslik.pack(fill="x", expand=True, pady=0)
        self._imsakiye_baslik.bind("<Button-3>", self.kopyala_menusu)
        self._imsakiye_baslik.bind("<Control-c>", lambda event: self.copy_text_from_widget(self._imsakiye_baslik))
        tablo_cerceve = ttk.Frame(self.pencere)
        tablo_cerceve.pack(pady=10, padx=10, fill="both", expand=True)
        icerik_frame = ttk.Frame(tablo_cerceve)
        icerik_frame.pack(fill="both", expand=True)
        columns = ("Tarih", "İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı")
        tarih_genisligi = self.bold_font.measure("28 Ağustos 2026 Pazartesi") + 24
        tree = ttk.Treeview(icerik_frame, columns=columns, show="headings", selectmode="extended", height=7)
        for col in columns:
            if col == "Tarih":
                tree.heading(col, text=col, anchor="w")
                tree.column(col, anchor="w", width=tarih_genisligi, stretch=False, minwidth=tarih_genisligi)
            else:
                tree.heading(col, text=col, anchor="center")
                tree.column(col, anchor="center", width=70, stretch=True, minwidth=55)
        scrollbar = ttk.Scrollbar(icerik_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.tag_configure("today", background="#A8DFB8", foreground="#1A1A1A", font=self.bold_font)
        self.imsak_tree = tree
        context_menu = tk.Menu(self.pencere, tearoff=0)
        context_menu.add_command(label="Kopyala", command=lambda: self.copy_treeview_selection(tree))
        def _tablo_menusu(event: tk.Event) -> None:
            iid = tree.identify_row(event.y)
            if not iid:
                return
            if iid not in tree.selection():
                tree.selection_set(iid)
            context_menu.tk_popup(event.x_root, event.y_root)
            context_menu.grab_release()
        tree.bind("<Button-3>", _tablo_menusu)
        tree.bind("<Control-c>", lambda event: self.copy_treeview_selection(tree))
        tree.bind("<Button-1>", lambda e: "break" if tree.identify_region(e.x, e.y) == "separator" else None)
    def _hicri_basligi_getir(self) -> None:
        hicri_metin = "🌙 " + self.model.clean_text(self.model.hicri_tarih_header()).strip()
        def _yaz():
            self._imsakiye_baslik.config(state="normal")
            self._imsakiye_baslik.delete(0, "end")
            self._imsakiye_baslik.insert(0, hicri_metin)
            self._imsakiye_baslik.config(state="readonly")
        TkManager.safe_after(0, _yaz, context="HicriBaslik")
        self.basligi_ayarla(self.model.ramazan_mi())
    @run_on_main_thread
    def basligi_ayarla(self, ramazan: bool) -> None:
        if ramazan:
            metin = f"🌙 Hoş geldin, Ramazan {self.model.yerel_simdi().year} ❤️"
            self.baslik_label.config(text=metin, foreground="#C47A00")
            self.pencere.title(f"{metin} - {self._dosya_adi}")
        else:
            self.baslik_label.config(text="🕌 Namaz Vakitleri", foreground="#1A6CA8")
            self.pencere.title(f"Namaz Vakitleri - {self._dosya_adi}")
    def _konsol_panelini_olustur(self) -> None:
        self.console_frame = ttk.Frame(self.pencere)
        if self.model.DEVELOPER_MODE:
            self.console_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        ttk.Separator(self.console_frame, orient="horizontal").pack(fill="x", padx=0, pady=(2, 0))
        header_frame = ttk.Frame(self.console_frame)
        header_frame.pack(side="top", fill="x", padx=0, pady=2)
        ttk.Label(header_frame, text="Konsol Paneli", font=self.bold_font, anchor="w").pack(side="left", padx=(5, 5))
        ttk.Button(header_frame, text="🗑️ Temizle", command=self.controller.clear_log, style="Custom.TButton").pack(side="right", padx=(5, 8), pady=1)
        console_subframe = ttk.Frame(self.console_frame)
        console_subframe.pack(side="top", fill="x", expand=False, padx=0, pady=0)
        console_scrollbar = ttk.Scrollbar(console_subframe, orient="vertical")
        console_scrollbar.pack(side="right", fill="y")
        self.ConsolePanel = tk.Text(console_subframe, font=("Consolas", 10),
                                    background="black", foreground="green",
                                    insertbackground="green", wrap="word",
                                    state="disabled", yscrollcommand=console_scrollbar.set,
                                    height=8)
        self.ConsolePanel.pack(side="left", fill="x", expand=True)
        console_scrollbar.config(command=self.ConsolePanel.yview)
        self.ConsolePanel.tag_configure("ERROR", foreground="red")
        self.ConsolePanel.tag_configure("WARNING", foreground="orange")
        self.ConsolePanel.tag_configure("INFO", foreground="#00A000")
        self.ConsolePanel.tag_configure("DEBUG", foreground="cyan")
        self.ConsolePanel.tag_configure("DEFAULT", foreground="#00A000")
        self.ConsolePanel.bind("<Button-3>", self.kopyala_menusu)
        self.ConsolePanel.bind("<Control-a>", self._konsolu_tumunu_sec)
        self.ConsolePanel.bind("<Control-c>", lambda event: self.copy_text_from_widget(self.ConsolePanel))
    def _konsolu_tumunu_sec(self, event: tk.Event) -> str:
        self.ConsolePanel.tag_add("sel", "1.0", "end")
        return "break"
    def _konsolu_periyodik_guncelle(self) -> None:
        if not (self.pencere and self.pencere.winfo_exists()):
            return
        if self.model.DEVELOPER_MODE and not self.model.log_buffer.empty():
            self.update_console_from_model()
        TkManager.safe_after(1000, self._konsolu_periyodik_guncelle, context="PeriodicConsoleUpdate")
    def _kapanisi_baglat(self) -> None:
        self.pencere.protocol("WM_DELETE_WINDOW", self._cikisi_onayla)
    def _cikisi_onayla(self) -> None:
        if safe_askyesno("⚠️ Çıkış", "Uygulamadan çıkmak istediğinize emin misiniz?"):
            self._pencereyi_kapat()
    def _pencereyi_kapat(self) -> None:
        try:
            if not (self.pencere and self.pencere.winfo_exists()):
                return
            if self.pencere.attributes("-fullscreen"):
                self.pencere.attributes("-fullscreen", False)
                self.pencere.update_idletasks()
            else:
                self.windowed_geometry = self.pencere.geometry()
            self.model.config_manager.set("pencere_boyutu", self._kaydedilecek_geometri())
            self.model.config_manager.save()
        except Exception as e:
            logging.error("Pencere kapanışında hata oluştu: %s", e)
        finally:
            try:
                if self.pencere and self.pencere.winfo_exists():
                    self.pencere.destroy()
            except Exception as e:
                logging.error("Tkinter penceresi kapatılırken hata oluştu: %s", e)
            self.pencere = None
            graceful_shutdown()
    def _kaydedilecek_geometri(self) -> str:
        mevcut = self.windowed_geometry if self.windowed_geometry else self.pencere.geometry()
        istenen_yukseklik = self._asgari_yukseklik()
        geom_match = GEOMETRY_RE.match(mevcut)
        if geom_match:
            genislik, yukseklik = int(geom_match.group(1)), int(geom_match.group(2))
            x_offset, y_offset = int(geom_match.group(3)), int(geom_match.group(4))
        else:
            logging.error("Geometri ayrıştırılamadı: %s", mevcut)
            genislik, yukseklik, x_offset, y_offset = 965, istenen_yukseklik, 480, 110
        yukseklik = max(yukseklik, istenen_yukseklik)
        geometri = f"{genislik}x{yukseklik}+{x_offset}+{y_offset}"
        logging.info("Kaydedilecek pencere geometrisi: %s", geometri)
        return geometri
    def on_configure(self, event: tk.Event) -> None:
        if event.widget is not self.pencere:
            return
        current_time = time.monotonic()
        if current_time - self._last_configure_time < 0.3:
            return
        self._last_configure_time = current_time
        try:
            if not self.pencere.attributes("-fullscreen"):
                self.windowed_geometry = self.pencere.geometry()
        except Exception as e:
            logging.exception("Pencere konfigürasyonu sırasında sorun: %s", e)
    def patch_messagebox_functions(self) -> None:
        def _limited_messagebox_wrapper(original_function: Callable, max_length: int = 1024) -> Callable:
            def wrapper(title: Optional[str] = None, message: Optional[str] = None, *args: Any, **kwargs: Any):
                if threading.current_thread() is not threading.main_thread():
                    logging.error("GUI messagebox fonksiyonu %s ana iş parçacığı dışında çağrıldı.", original_function.__name__)
                    return None
                if message is not None and len(message) > max_length:
                    message = message[:max_length] + "..."
                return original_function(title, message, *args, **kwargs)
            return wrapper
        functions = ["showinfo", "showwarning", "askquestion", "askokcancel", "askyesno", "askretrycancel", "showerror"]
        for func_name in functions:
            original_func = getattr(messagebox, func_name)
            if getattr(original_func, "_iftar_sarmalandi", False):
                continue
            limited_func = _limited_messagebox_wrapper(original_func, max_length=1024)
            limited_func._iftar_sarmalandi = True
            setattr(messagebox, func_name, limited_func)
    def get_window_geometry(self) -> str:
        saved_geom = self.model.config_manager.get("pencere_boyutu", "")
        if saved_geom and GEOMETRY_RE.match(saved_geom):
            return saved_geom
        width = 965
        height = self._asgari_yukseklik()
        sw = self.pencere.winfo_screenwidth()
        sh = self.pencere.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        return f"{width}x{height}+{x}+{y}"
    def alt_pencereyi_ortala(self, alt_pencere: tk.Toplevel) -> None:
        alt_pencere.update_idletasks()
        w, h = alt_pencere.winfo_reqwidth(), alt_pencere.winfo_reqheight()
        px, py = self.pencere.winfo_x(), self.pencere.winfo_y()
        pw, ph = self.pencere.winfo_width(), self.pencere.winfo_height()
        alt_pencere.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
    def create_fonts(self, root: tk.Tk) -> None:
        self.default_font = tkFont.Font(root, family="Segoe UI Emoji", size=10)
        self.bold_font = tkFont.Font(root, family="Segoe UI Emoji", size=10, weight="bold")
        self.large_bold_font = tkFont.Font(root, family="Segoe UI Emoji", size=14, weight="bold")
    @run_on_main_thread
    def arayuzu_guncelle(self, ezan_saatleri: Dict[str, str]) -> None:
        if self.prayer_labels is None:
            self.prayer_labels = []
            self.prayer_time_labels = []
            for i in range(6):
                lbl = ttk.Label(self.vakit_cerceve, text=self._label_texts[i], font=self.default_font, anchor="center", justify="center")
                lbl.grid(row=0, column=i, padx=2, pady=5, sticky="nsew")
                self.prayer_labels.append(lbl)
                lbl2 = ttk.Label(self.vakit_cerceve, text="⏳", font=self.default_font, anchor="center", justify="center")
                lbl2.grid(row=1, column=i, padx=2, pady=5, sticky="nsew")
                self.prayer_time_labels.append(lbl2)
                self.vakit_cerceve.columnconfigure(i, weight=1)
        if not ezan_saatleri:
            return
        saatler = tuple(ezan_saatleri.get(v, "-") for v in self._vakitler_ing)
        tz_str = ezan_saatleri.get("timezone")
        tz = self.model.zaman_dilimi()
        now = get_utc_now().astimezone(tz)
        now_date = now.date()
        time_cache = self._time_parse_cache
        current_tp_key = (now_date, tz_str, saatler)
        last_tp_key = self._tp_key
        last_tp_values = self._tp_values
        if last_tp_key == current_tp_key and last_tp_values is not None:
            today_prayers = list(last_tp_values)
        else:
            today_prayers = []
            append_tp = today_prayers.append
            for time_str in saatler:
                t = time_cache.get(time_str)
                if t is None:
                    try:
                        t = datetime.strptime(time_str[:5], "%H:%M").time()
                    except ValueError:
                        append_tp(None)
                        continue
                    if len(time_cache) > 100:
                        time_cache.pop(next(iter(time_cache)))
                    time_cache[time_str] = t
                append_tp(datetime.combine(now_date, t, tzinfo=tz))
            self._tp_key = current_tp_key
            self._tp_values = tuple(today_prayers)
        current_index = -1
        next_index = -1
        if today_prayers[0] is not None and now < today_prayers[0]:
            if today_prayers[-1] is not None:
                current_index = 5
            next_index = 0
        elif today_prayers[-1] is not None and now > today_prayers[-1]:
            current_index = len(today_prayers) - 1
            next_index = 0
        else:
            for i, prayer_time in enumerate(today_prayers):
                if prayer_time is None:
                    continue
                if prayer_time <= now:
                    current_index = i
                elif prayer_time > now and next_index == -1:
                    next_index = i
        pair = (current_index, next_index)
        if self._last_saatler == saatler and self._last_vakit_indices == pair:
            return
        if self._last_vakit_indices != pair:
            logging.info("Mevcut vakit indeksi: %s, Sonraki vakit indeksi: %s", current_index, next_index)
            self._last_vakit_indices = pair
        labels = self.prayer_labels
        time_labels = self.prayer_time_labels
        default_font = self.default_font
        bold_font = self.bold_font
        pl_state = self._pl_state
        pl_time_state = self._pl_time_state
        label_texts = self._label_texts
        for i in range(6):
            text_str = label_texts[i]
            if i == next_index:
                fg_color = "#C47A00"
                font_to_use = default_font
            elif i == current_index:
                fg_color = "#007040"
                font_to_use = bold_font
            else:
                fg_color = "#888888"
                font_to_use = default_font
            new_label_state = (text_str, font_to_use, fg_color)
            if pl_state[i] != new_label_state:
                labels[i].config(text=text_str, font=font_to_use, foreground=fg_color)
                pl_state[i] = new_label_state
            new_time_state = (saatler[i], font_to_use, fg_color)
            if pl_time_state[i] != new_time_state:
                time_labels[i].config(text=saatler[i], font=font_to_use, foreground=fg_color)
                pl_time_state[i] = new_time_state
        self._last_saatler = saatler
        
    @run_on_main_thread
    def show_info(self, msg: str) -> None:
        safe_showinfo("Bilgi", msg)
    @run_on_main_thread
    def show_error(self, title: str, msg: str) -> None:
        safe_showerror(title, msg)
    @run_on_main_thread
    def update_console_from_model(self, max_lines: int = 1000) -> None:
        if not self.model.DEVELOPER_MODE:
            return
        try:
            if not (self.ConsolePanel and self.ConsolePanel.winfo_exists()):
                return
        except Exception as e_check:
            logging.error("Konsol durumu kontrol edilirken hata: %s", e_check)
            return

        new_messages = []
        log_read_limit = 500
        while len(new_messages) < log_read_limit:
            try:
                new_messages.append(self.model.log_buffer.get_nowait())
            except queue.Empty:
                break

        if new_messages:
            try:
                self.ConsolePanel.configure(state="normal")

                current_line_count_str = self.ConsolePanel.index("end-1c").split('.')[0]
                try:
                    current_line_count = int(current_line_count_str)
                except ValueError:
                    current_line_count = 0

                lines_to_be_added = sum(msg.count('\n') for _level, msg in new_messages)

                if current_line_count + lines_to_be_added > max_lines:
                    lines_to_delete = (current_line_count + lines_to_be_added) - max_lines
                    delete_end_index = f"{lines_to_delete + 1}.0"
                    self.ConsolePanel.delete("1.0", delete_end_index)

                for level, msg in new_messages:
                    tag_to_apply = level if level in ("ERROR", "WARNING", "INFO", "DEBUG") else "DEFAULT"
                    self.ConsolePanel.insert("end", msg, (tag_to_apply,))

                self.ConsolePanel.see("end")

            except tk.TclError as e_tcl:
                logging.error("Konsol güncellenirken TclError: %s", e_tcl)
            except Exception as e_main:
                logging.exception("Konsol güncellenirken beklenmeyen hata: %s", e_main)
            finally:
                try:
                    if self.ConsolePanel and self.ConsolePanel.winfo_exists():
                        self.ConsolePanel.configure(state="disabled")
                except Exception as e_final:
                    logging.error("Konsol state'i 'disabled' yapılırken hata: %s", e_final)

    @run_on_main_thread
    def clear_console_panel(self) -> None:
        if self.ConsolePanel:
            try:
                self.ConsolePanel.configure(state="normal")
                self.ConsolePanel.delete("1.0", "end")
                self.ConsolePanel.configure(state="disabled")
            except Exception as e:
                logging.exception("ConsolePanel temizlenirken sorun: %s", e)
    def create_logged_button(self, master: tk.Widget, **kwargs: Any) -> ttk.Button:
        cmd = kwargs.get("command")
        text_for_log = kwargs.get("text", "Buton")
        def new_callback(*args: Any, **kw: Any) -> Any:
            self.controller.log_message(f"Butona tıklandı: {text_for_log}")
            if cmd:
                return cmd(*args, **kw)
        kwargs["command"] = new_callback
        kwargs.pop("font", None)
        style_name = "Custom.TButton"
        kwargs["style"] = style_name
        return ttk.Button(master, **kwargs)
    def copy_treeview_selection(self, tree_widget: ttk.Treeview) -> None:
        satirlar = ["\t".join(map(str, tree_widget.item(item, "values"))) for item in tree_widget.selection()]
        if not satirlar:
            return
        try:
            self.pencere.clipboard_clear()
            self.pencere.clipboard_append("\n".join(satirlar))
        except tk.TclError as e:
            logging.error("Takvim verisi panoya kopyalanamadı: %s", e)
            safe_showerror("Kopyalama Hatası", f"Takvim verisi panoya kopyalanamadı:\n{e}")
    @run_on_main_thread
    def update_sistem_saati_label(self, icon: str, msg: str, bitti: bool = True) -> None:
        if self.sistem_saati_label:
            self.sistem_saati_label.config(text=f"{icon} Sistem Saati Kontrolü: {msg}")
        if self._compare_button:
            self._compare_button.config(state="normal" if bitti else "disabled", text="🔄 Karşılaştır" if bitti else "⏳")

_kapanis_baslatildi = threading.Event()

def graceful_shutdown():
    if _kapanis_baslatildi.is_set():
        return
    _kapanis_baslatildi.set()
    if globals().get("model") is None or globals().get("view") is None:
        sys.exit(0)
    try:
        model.executor.shutdown(wait=False, cancel_futures=True)
        model.GLOBAL_SESSION.close()
        if view.pencere is not None and view.pencere.winfo_exists():
            view.pencere.destroy()
    except Exception as e:
        logging.error("Kapanış sırasında kaynaklar serbest bırakılamadı: %s", e)
    logging.info("Uygulama kapatıldı.")
    listener = getattr(model, "log_queue_listener", None)
    if listener:
        try:
            listener.stop()
        except Exception as e:
            logging.debug("Log dinleyicisi durdurulamadı: %s", e)
    handler = getattr(model, "log_file_handler", None)
    if handler is not None:
        try:
            handler.close()
        except Exception:
            pass
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    logging.shutdown()
    os._exit(0)

if __name__ == "__main__":
    base_dir = BASE_DIR
    model = IftarModel(base_dir=base_dir, default_timeout=10, short_timeout=5, default_retries=3, backoff_factor=2)
    CHECK_MODULE_UPDATES = parse_bool(model.config_manager.get("check_module_updates", "False"))
    if CHECK_MODULE_UPDATES:
        ModuleManager.ensure_required_modules(required_modules)
    controller = IftarController(model=model)
    view = IftarView(controller=controller, model=model)
    controller.set_view(view)
    def handle_signal(signum, frame):
        logging.info("Kapatma sinyali alındı (%s).", signum)
        graceful_shutdown()
    signal_mod.signal(signal_mod.SIGINT, handle_signal)
    try:
        signal_mod.signal(signal_mod.SIGTERM, handle_signal)
    except (AttributeError, ValueError):
        logging.warning("SIGTERM bu platformda desteklenmiyor.")
    controller.run()

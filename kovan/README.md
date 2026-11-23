# KOVAN

KOVAN, farklı cihazların kaynaklarını ve yeteneklerini tanıyarak görevleri
uygun cihazlara yerleştirmeyi hedefleyen dağıtık işlem sistemidir.

**Bu sürüm:** v0.2–v0.4 altyapısı. Controller tek süreçtir; Python worker'lar
ayrı süreçlerdir. Merkezi veritabanı SQLite'tır.

## Gerçekte uygulanmış olanlar

- Cihaz kaydı, heartbeat, online/offline değerlendirmesi ve cihaz raporu.
- Yetenek, kaynak, bağlantı, pil/ısınma politikası ve önceliğe göre scheduler.
- Atomik görev claim'i; aynı worker için bir aktif görev sınırı.
- Deneme başına `lease_id`, timeout, yeniden atama, sınırlı retry ve backoff.
- Dört izinli görev türü: `sha256_file`, `word_count`, `pi_monte_carlo`, `prime_count`;
  shell/kod çalıştırma yok.
- Telefon/tablet bağlama: QR kodla açılan tarayıcı sayfası (kurulum gerekmez).
- Benchmark: aynı π hesabını 1 cihazda ve tüm cihazlarda çalıştırıp süre karşılaştırır.
- Worker dosya erişimi için izinli dizin ve dosya boyutu sınırı.
- Eski SQLite verileri için otomatik şema geçişi.
- PySide6 masaüstü arayüzü (`run_kovan.py`): controller + yerel worker + panel.

**Uygulanmamış olanlar:** Yerel Android uygulaması, ESP32 worker/protokol endpoint'i,
gerçek GPU hesaplaması, çalışan Python thread'ini zorla durdurma, çoklu eşzamanlı
worker görevi ve uzaktan erişilebilir web paneli.

## Hızlı başlangıç: arayüzle (PyCharm)

1. PyCharm'da **File > Open** ile proje klasörünü aç.
2. **Settings > Project > Python Interpreter** bölümünden yeni bir
   sanal ortam (venv) seç ve terminalde paketleri kur:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. `run_kovan.py` dosyasına sağ tıkla ve **Run 'run_kovan'** de.

Bu tek komut controller'ı, bu bilgisayardaki yerel worker'ı ve pencereyi
birlikte başlatır. Gizli token'lar ilk açılışta otomatik üretilip
`.kovan-secrets/` klasörüne yazılır; elle bir şey ayarlamana gerek yoktur.
Pencerede beş sayfa vardır:

- **Panel:** Özet sayılar, cihaz kartları (CPU/RAM/pil, anlık görev) ve son görevler.
- **Görevler:** Durum filtreli görev listesi; hangi cihazın aldığı, sonuç veya hata.
- **Yeni görev:** Metin, dosya, π ve asal sayma görevi gönderme; "10 örnek görev" demosu.
- **Benchmark:** 1 cihaz ve tüm cihazlar için süre karşılaştırması.
- **Cihaz bağla:** Telefon için QR kod, bilgisayar için hazır komutlar.

Yerel worker güvenlik için yalnızca proje içindeki `data/` klasörünü okur.
Başka bir dosyayı seçersen arayüz, kopyalanması için onay ister.

### Telefon / tablet bağlama

1. Arayüzde **Cihaz bağla** sayfasını aç ve **Ağ erişimini aç** düğmesine bas.
   Windows güvenlik duvarı sorarsa **Özel ağlar**'a izin ver.
2. Telefon ve bilgisayar aynı Wi-Fi ağında olsun. Telefonun kamerasıyla QR kodu
   okut ve açılan bağlantıya dokun. Sayfa kendiliğinden eşleşir (kod elle de
   girilebilir).
3. Telefon **Cihazlar** listesinde görünür ve görev almaya başlar.

Bilmen gerekenler:

- Eşleştirme kodu 5 dakika geçerli ve **tek kullanımlıktır**; kayıt token'ı
  telefona hiç gönderilmez. Başarısız denemeler dakikada 10 ile sınırlıdır.
- Telefon yalnızca `pi_monte_carlo` ve `prime_count` görevlerini alır; dosya
  görevleri telefona gitmez.
- Görevler **sayfa açıkken ve ekran uyanıkken** çalışır. Ekran kapanır veya
  sekme arka plana atılırsa tarayıcı sayfayı yavaşlatır/durdurur; görev süresi
  dolunca başka cihaza verilir.
- Şifresiz HTTP'de tarayıcılar pil, bellek ve ekran-uyanık bilgisini
  vermez. Bu yüzden telefonun pil değeri boş görünür ve ağır görev almaz.
- Bu yöntem Termux/uygulama kurmadan çalışır; Android 7 üstü güncel bir Chrome
  veya benzeri tarayıcı yeterlidir. Eski cihazlarda tarayıcı sürümü
  doğrulanmadı.

### Başka bir bilgisayar bağlama

**Cihaz bağla** sayfası hazır PowerShell komutlarını ve kayıt token'ını kopyalama
düğmesini verir. Arayüz kapalıyken komut satırı için aşağıdaki "PowerShell
kurulumu" bölümlerine bak. Ağ erişimi açıkken iletişim şifresiz HTTP'dir;
yalnızca güvenilir ev ağında kullan. Ayar `.kovan-secrets/settings.json`
dosyasında saklanır, istersen `python run_kovan.py --lan` ile de açılır.

### Benchmark

**Benchmark** sayfası büyük bir π hesabını parçalara böler. Önce "Sadece bu
bilgisayar", sonra "Tüm cihazlar" seçeneğiyle çalıştırınca süreleri ve
hız farkını tabloda görürsün. Sonuç; cihaz sayısına, cihazların gerçek
hızına ve parça sayısına bağlıdır. İş dağıtımı "çek" (pull) modelidir:
yavaş bir cihaz, son parçalardan birini alırsa toplam süreyi uzatabilir.
Parça sayısını artırmak bu etkiyi azaltır. Hız karşılaştırmasını aynı
makinede çalışan birden fazla worker ile yapma; CPU'yu paylaşırlar.

## Gereksinimler

- Python 3.12+
- Windows, Linux veya macOS üzerinde Python worker
- `requirements.txt` paketleri

Raspberry Pi için Linux/Python/`psutil` kurulabilen bir ortam gerekir; bu
sürümde ayrı bir Raspberry Pi dağıtımı veya donanım testi yoktur.

## PowerShell kurulumu

Proje kökünde:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Aktivasyon engellenirse yalnızca mevcut PowerShell oturumu için:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`.env.example` değişkenlerin örneğidir; `.env` otomatik okunmaz.

### Token oluşturma

Geliştirme makinesinde yönetici ve kayıt token'larını **farklı** üret:

```powershell
New-Item -ItemType Directory .kovan-secrets -Force | Out-Null

python -c "import secrets; print(secrets.token_urlsafe(32))" |
  Set-Content -NoNewline .kovan-secrets\admin.txt

python -c "import secrets; print(secrets.token_urlsafe(32))" |
  Set-Content -NoNewline .kovan-secrets\registration.txt
```

Bu dizini paylaşma veya Git'e ekleme. Uzak worker'a yalnızca **kayıt token'ı**
gerekir; yönetici token'ı verilmez.

### Terminal 1: Controller

```powershell
$env:KOVAN_DB_PATH = "kovan.db"
$env:KOVAN_ADMIN_TOKEN =
  (Get-Content .kovan-secrets\admin.txt -Raw).Trim()
$env:KOVAN_REGISTRATION_TOKEN =
  (Get-Content .kovan-secrets\registration.txt -Raw).Trim()
$env:KOVAN_DEVICE_OFFLINE_SECONDS = "35"

python -m uvicorn controller.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2: Worker

Worker'ın okuyabileceği **sınırlı** bir dizin oluştur:

```powershell
New-Item -ItemType Directory data -Force | Out-Null

$env:KOVAN_CONTROLLER_URL = "http://127.0.0.1:8000"
$env:KOVAN_DEVICE_ID = "pc-1"
$env:KOVAN_DEVICE_TYPE = "desktop"
$env:KOVAN_REGISTRATION_TOKEN =
  (Get-Content .kovan-secrets\registration.txt -Raw).Trim()
$env:KOVAN_CAPABILITIES = "sha256_file,word_count"
$env:KOVAN_ALLOWED_DIRS = (Resolve-Path .\data).Path

python -m worker.main
```

İlk kayıttan sonra cihaz token'ı varsayılan olarak
`.kovan-secrets/worker-pc-1.json` dosyasına kaydedilir. Aynı bilgisayardaki
başka worker için farklı `KOVAN_DEVICE_ID` kullan. Eski sürümün
`.kovan_worker_token` dosyası, `device_id` eşleşiyorsa okunabilir.

**Windows notu:** Worker token dosyasını yalnızca ilgili kullanıcı hesabının
erişebildiği yerde tut. POSIX'te dosya `0600`, dizin `0700` yapılır; Windows
ACL yapılandırmasını bu sürüm otomatik yönetmez.

## Görev oluşturma

Yeni bir PowerShell terminalinde:

```powershell
$headers = @{
  "X-Admin-Token" =
    (Get-Content .kovan-secrets\admin.txt -Raw).Trim()
}
```

Metin sayımı:

```powershell
$body = @{
  task_type = "word_count"
  payload = @{ text = "merhaba KOVAN dünya" }
  requirements = @{
    priority = 20
    min_ram_bytes = 1048576
    cpu_intensity = "low"
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/tasks" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Yerel dosya görevi:

```powershell
"merhaba KOVAN" | Set-Content .\data\ornek.txt
$file = (Resolve-Path .\data\ornek.txt).Path

$body = @{
  task_type = "sha256_file"
  payload = @{ path = $file }
  requirements = @{
    allowed_device_ids = @("pc-1")
    priority = 10
  }
  timeout_seconds = 60
  max_attempts = 3
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/tasks" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

**Önemli:** Dosya yolu worker cihazında geçerli olmalıdır. Farklı işletim
sistemlerinde aynı mutlak yolun var olduğunu varsayma. Yerel dosya görevlerinde
`allowed_device_ids` ile ilgili cihazı seç.

Görev ve cihaz inceleme:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/1" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000/tasks" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000/devices" -Headers $headers
```

## Gereksinimler ve yerleştirme

`requirements` alanındaki seçenekler:

- `min_ram_bytes`: Worker'ın **kullanılabilir** RAM'i.
- `min_cpu_cores`: Asgari mantıksal çekirdek.
- `requires_gpu`: Yalnızca compute-capable GPU bildiren uygun PC'ye yerleştirir.
  **Mevcut görevlerde GPU hızlandırması yapmaz.**
- `required_capabilities`: Ek izinli yetenekler.
- `estimated_duration_seconds`: Tahmin; timeout'tan büyük olamaz.
- `priority`: 0–100. Yüksek öncelikli hazır görevler önce değerlendirilir.
- `allowed_device_types`, `allowed_device_ids`: Yerleştirme sınırları.
- `cpu_intensity`, `heavy`: Ağır iş politikasını etkiler.

Bilinmeyen donanım ölçümleri `null` tutulur. RAM/çekirdek şartı olan bir görev,
ilgili ölçüm bilinmiyorsa yerleştirilmez. Ağır mobil görev için şarj, pil,
normal termal durum ve yeterli kapasite ölçümleri zorunludur. Masaüstü worker'ı
termal durumu otomatik olarak bildirmez. Worker'ın GPU bildirimi ancak
`KOVAN_GPU_COMPUTE_NAME` açıkça ayarlanırsa oluşur; gerçek donanım doğrulaması
veya GPU yürütücüsü değildir.

Scheduler, worker-pull modeli içinde hazır görevleri öncelik sırasıyla tarar
ve o andaki raporlara göre en uygun **çevrimiçi, boş** cihazı seçer. Başka
cihazın çektiği istek, o cihaz için ayrılan görevi alamaz; kendine uygun daha
düşük öncelikli görevi alabilir. Seçilen cihaz çevrimiçi görünüp poll etmeyi
bırakırsa, offline eşiği dolana dek görev bekleyebilir. Ölçümler heartbeat
aralığı kadar eski olabilir; scheduler gerçek zamanlı kaynak rezervasyonu
yapmaz.

## Lease, tekrar deneme ve sonuçlar

Her claim yeni bir `lease_id` üretir. Sonuç isteğinde bu değer zorunludur.
Geç gelen eski deneme, görev aynı worker'a tekrar verilmiş olsa bile reddedilir.
Süresi dolan veya `retryable=true` ile bildirilen hata, `max_attempts`
dolmadıysa 1, 2, 4 ... en çok 30 saniye beklemeyle yeniden kuyruğa alınır.
Worker'ın bildirdiği kalıcı dosya/UTF-8/yetki hataları tekrar denenmez.

Controller lease süresini uygular fakat çalışan Python thread'ini öldürmez.
Bir worker hâlâ okurken lease dolarsa başka worker aynı dosyayı okuyabilir.
Bu nedenle yürütme **at-least-once** karakterindedir; yalnızca sonucun
kabulü deneme kimliğiyle korunur. MVP görevleri salt-okunurdur. Gelecekte
yan etkili görev eklenirse idempotency ve harici yan etki koordinasyonu ayrıca
tasarlanmalıdır. Uzun işler için uygun `timeout_seconds` seç.

## Eski sürümden yükseltme

1. Eski controller ve worker süreçlerini durdur.
2. `kovan.db` ve worker token dosyalarını yedekle.
3. Dosyaları güncelle ve yeni paketleri kur.
4. Yeni controller'ı başlat. Eski `tasks`/`workers` kayıtlarına alanlar eklenir;
   kimlikler ve cihaz token özetleri korunur.
5. Worker'ları yeni sürümle başlat.

Eski sürümde zaten `running` olan ve `lease_id` taşımayan görevler,
sonuçları güvenle eşleştirilemeyeceği için retry kuyruğuna alınır veya deneme
sınırı dolmuşsa `failed` olur. **Eski worker API gövdeleri yeni controller
ile uyumlu değildir.** Önce eski worker süreçlerini durdur.

Kayıp cihaz token'ı için eski worker'ı durdur, ardından yönetici olarak:

```powershell
$reset = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/devices/pc-1/reset-token" `
  -Headers $headers

# Yalnızca ilgili worker terminalinde kullan; ekrana yazdırma.
$env:KOVAN_WORKER_TOKEN = $reset.token
```

Token sıfırlama çalışan lease'i bırakır; eski token'ı geçersiz kılar.
Yeni token'ı worker için güvenli şekilde sakla. Token yanıtı yalnızca
sıfırlama isteğinde döner.

## Testler

Proje kökünde, sanal ortam aktifken:

```powershell
python -m pytest -q
```

## Güvenlik ve platform sınırları

- Controller'ı gizli tokenlar olmadan başlatmak hata verir.
- Varsayılan örnek yalnızca `127.0.0.1` üzerinde HTTP kullanır. Uzak
  cihazlar için TLS sağlayan güvenilir bir proxy/VPN ve ağ erişim kontrolü
  gerekir; token'ları düz HTTP ile internete gönderme.
- Telefon sayfası (`/phone`) gizli bilgi içermez; eşleştirme kodu adresin `#` kısmında
  taşınır ve kullanılınca adres çubuğundan silinir.
- Cihazın bildirdiği donanım bilgileri **öz-beyandır**; düşmanca worker'a
  karşı doğrulanmış güvenlik sınırı değildir.
- POSIX dosya açma, symlink'leri dizin-descriptor zinciriyle engeller.
  Windows kapsam/symlink/junction denetimi vardır; dosya sistemini eşzamanlı
  değiştirebilen kötü niyetli yerel süreçlere karşı tam TOCTOU garantisi
  verilmez. Worker'ın izinli dizinini güvenilir kullanıcıya ait tut.
- Dosya görevleri mutlak yollarla çalışır; worker izinli dizin dışını okumaz.
- SQLite tek controller süreci için tasarlanmıştır. Çoklu `uvicorn --workers`
  ile çalıştırma bu sürümde desteklenen dağıtım modeli değildir.

## Android: sonraki aşama, mevcut destek değil

Android 7+ için olası yollar Termux üzerinde deneysel Python worker veya
Android uygulaması içindeki yerel worker'dır. Bu sürümde Android 7 cihazında
Termux/Python 3.12/`psutil` uyumluluğu **doğrulanmadı**. Android sürümü,
dağıtılan Termux sürümü ve paket erişilebilirliği cihaz üzerinde ayrıca
kontrol edilmelidir.

Uzun süreli ve güvenilir çalışma için yerel uygulama, uygun foreground
service, pil/termal Android API'leri ve Doze/arka plan kısıtları değerlendirilmelidir.
Mevcut cihaz modeli ve scheduler mobil pil/termal verisini kabul eder; bu,
Android worker'ın hazır olduğu anlamına gelmez.

## ESP32: tasarım yönü, çalışan protokol değil

ESP32 normal Python worker sayılmaz. Gelecek hafif protokol tasarımı:
TLS destekli cihaz kaydı/provizyonlama; cihaz başına token; küçük,
sürüm numaralı heartbeat/claim/result mesajları; deneme kimliği ve
`lease_id`; özel mikrodenetleyici görev izin listesi; küçük payload ve
sonuç sınırları. Donanım ve TLS kapasitesine göre gateway gerekip
gerekmediği ayrıca değerlendirilmelidir.

**Bu sürümde** ESP32 endpoint'i, ESP32 istemcisi veya ESP32 görev türü yoktur;
`microcontroller` raporu mevcut Python görevlerini ilan edemez.

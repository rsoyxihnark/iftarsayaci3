# Değişiklik Günlüğü

## 1.2.2

- Namaz vakitleri alınamadığında Namaz Vakitleri panelinde artık önceki günün ya da önceki konumun saatleri kalmıyor.
- İftar sonrası sayaçta, yarının imsak saati alınamadığında da geri sayımın bittiği saat yazıyor.
- Geliştirici Modu'nda Konsol Paneli ve kayıt dosyasındaki satırlar, hepsi aynı yeri değil, artık geldikleri kod satırını gösteriyor.

## 1.2.1

- Pencere artık kapatıldığı yükseklikte açılıyor, kendiliğinden uzamıyor.
- Pencere, panellerin sığması için gereken yükseklikten daha kısa yapılamıyor, Geliştirici Modu açıkken bu yükseklik Konsol Paneli'ni de kapsıyor.
- Namaz vakitleri alınamadığında, pencere simge durumundan geri getirildiğinde ilerleme çubuğu yeniden yükleniyormuş gibi görünmüyor.

## 1.2.0

- IftarSayaci.exe dosyasının sürüm ve ürün bilgisi artık Windows'ta dosyanın özelliklerinde ve Dosya Gezgini'nin Dosya sürümü sütununda görünüyor.

## 1.1.7

- Konum başka bir saat dilimine değiştirildiğinde vakitler artık her zaman yeni konumun saat dilimine göre hesaplanıyor.

## 1.1.6

- Geliştirici modunda konsol paneli, uzun hata kayıtları bir anda geldiğinde de eski satırları atıyor ve aşırı büyümüyor.

## 1.1.5

- Bağlantı koptuğunda konsol paneline aynı uyarı tekrar tekrar yazılmıyor, sunucuya yeniden bağlanma denemesi de bildirilen süreden geç başlamıyor.
- Aktif konum satırından imleç ayrıldığında adres sorgusu artık sürdürülmüyor, namaz vakitleri ve takvim bu yüzden geç yenilenmiyor.

## 1.1.4

- Hicri ay bilgisi eksik geldiğinde de tanınıyor, Ramazan karşılaması ve o aya ait imsakiye takvimi doğru görüntüleniyor.
- Otomatik konum servisine ulaşılamaması artık namaz vakitlerinin alınmasını engellemiyor.

## 1.1.3

- Otomatik konum alınamadığında uygulama artık bunu bildiriyor.
- Ayar dosyası bir metin düzenleyicide kaydedildikten sonra da okunuyor, kayıtlı konum ve yöntem varsayılanlara dönmüyor.
- Geliştirici modu açılıp kapatılırken pencere, seçtiğiniz yüksekliği koruyarak yalnızca konsol paneli kadar büyüyüp küçülüyor.
- Şehir adı alınamadığında aktif konum satırında artık fazladan boşluk ve iki nokta görünmüyor.

## 1.1.2

- Hicri tarih hesabı artık yalnızca güncel takvim kütüphanesiyle yapılıyor, desteği bırakılmış eski kütüphaneye geri dönülmüyor.

## 1.1.1

- Pencere, kapatıldığı yerde ve boyutta yeniden açılıyor.
- Açılışta modül güncellemelerini kontrol etme seçeneği açıkken uygulama artık kendi kopyalarını açmıyor.
- Hakkında penceresi yüklü kütüphanelerin sürümlerini eksiksiz gösteriyor.
- Pencere başlığında artık programın kendi adı yazıyor.
- Otomatik konum sorgusu geç tamamlandığında bulduğu sonuç, bu arada elle seçilen konumun üzerine yazılmıyor.

## 1.1

- Ayarlar ve günlük dosyası artık programın bulunduğu klasöre yazılıyor.
- Program kapatılıp yeniden açıldığında seçilen konum ve hesaplama yöntemi korunuyor.
- .env dosyası da programın bulunduğu klasörden okunuyor.

## 1.0

- İftara ve sahura kalan süre, geçen sürenin yüzdesiyle birlikte canlı olarak gösteriliyor.
- İmsak, Güneş, Öğle, İkindi, Akşam ve Yatsı vakitleri seçili konum için günlük olarak listeleniyor.
- Konum otomatik olarak bulunuyor, dilediğinizde elle de girilebiliyor.
- Namaz vakitleri on ayrı hesaplama yöntemiyle hesaplanabiliyor.
- İçinde bulunulan hicri aya ait imsak takvimi görüntülenebiliyor.
- Bilgisayarın saati internet saat sunucusuyla karşılaştırılıp aradaki sapma bildiriliyor.
- Seçilen konum ve hesaplama yöntemi kapanışta kaydediliyor, uygulama yeniden açıldığında geri yükleniyor.
- Uygulama içindeki konsol paneli yapılan işlemleri anlık olarak gösteriyor.
- Hakkında penceresi artık uygulamanın sürümünü de gösteriyor.
- Ekrandaki metinlerde uzun tire yerine virgül ve iki nokta kullanılıyor.
- Uygulama, kurulum gerektirmeyen tek dosyalık Windows programı olarak indirilebiliyor.

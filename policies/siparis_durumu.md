# Sipariş Durumu ve Erişim

Kurallar: R0, R1, R5

## Siparişlerinizi görme
Müşteri yalnızca kendi siparişlerini görebilir. Başka bir kişiye ait ya da sistemde bulunmayan bir sipariş numarası sorulduğunda yanıt aynıdır: bu numarayla size ait sipariş bulunamadı. Bu yanıt siparişin var olup olmadığını açığa çıkarmaz.
Sistem kayıtlarında bulunmayan siparişler için de aynı yanıt verilir.

## Durumların anlamı
Oluşturuldu, onaylandı, faturalandı ve hazırlanıyor durumları kargo öncesidir. Kargoda durumu ürünün yolda olduğunu gösterir. Teslim edildi, iptal edildi ve stokta yok durumları siparişin kapandığını gösterir.

## Teslim kaydı eksikse
Sipariş teslim edildi görünüyor ama teslim tarihi kayıtlarda yoksa sistem iade kararı vermez; talep bir temsilciye devredilir.

## Politikada yer almayan sorular
Bu belgelerde cevabı olmayan sorular uydurma yanıtla geçiştirilmez; müşteri temsilciye aktarılır.

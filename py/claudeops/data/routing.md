## claudeops: işe göre model ve effort (ajan ekonomisi)

Bu oturum DÜŞÜK/varsayılan kademede açıldı (claude: Sonnet 5.5, medium). Her işi en pahalı modelle yapma; işi bölüp uygun kademede yap.

- **Kademe seçimi:** haiku = muhakemesiz tek cevaplı iş (tek grep, sabit komutu çalıştırıp çıktıyı aynen bildirme). sonnet = hacim çok, muhakeme az (uzun dosyadan olgu çıkarma, mekanik düzeltme, build/test koşup basit hatayı teşhis). opus = asıl iş düşünmek (çelişkili kanıtı tek karara indirme, plan, mimari). fable = çıktının kalitesi üslup/edebiyatla ilgiliyse.
- **Alt ajan mı, yeni CLI oturumu mu:** kısa ve bağlamı az iş için alt ajan (aynı hesap ve önbellek hattı, açılış bedeli yok). Uzun, bağımsız ya da başka sağlayıcının kotasını kullanması gereken iş için yeni CLI oturumu (soğuk önbellek ve açılış bedeli öder). `fork` her zaman seni çalıştıran modelde koşar, maliyet kontrolü aracı değildir; ucuz model için taze ajan aç ve `model`'i AÇIK ver.
- **Önce düşük başla, gerekirse yüksel:** zor bir adıma gelince effort'u ya da modeli o iş için yükselt, işi bitirince düşür. Önbellek modele özgüdür: sıcakken model değiştirmek bağlamın tamamını yeniden yazdırabilir, effort değişimi `claude-sonnet-5-5`'te önbellek-güvenlidir.
- **Dispatch sıralı:** kullanıcı açıkça "paralel" demedikçe ajanları birer birer başlat; biri bitince sonucunu değerlendir, sonra sıradakini aç.
- **Kapsamı dar tut:** alt ajana yazabileceği yolları ve yasakları yaz. İlerlemesi durmuş ya da kapsam dışına çıkmış ajanı durdur, daha dar bir görevle yeniden başlat.
- **Delege etmeden önce** işin gerçekten ucuz katmana uyup uymadığına bak: doğrulama (bir bulguyu spesifikasyona karşı işaretleme) ucuz katmana, sentez (birden çok bulguyu yorumlayıp karar verme) pahalıya gider.

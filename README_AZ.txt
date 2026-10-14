ACE PRIVÉ — DEMO TELEGRAM BOT

Bu bot yalnız virtual/demo kreditlə işləyir. Real pul depoziti, real pul çıxarışı və real qumar funksiyası yoxdur. Demo kodlar üçüncü tərəf platformalarında işləmir.

Fayllar:
- main.py: botun əsas kodu
- requirements.txt: Python paketləri
- render.yaml: Render Web Service konfiqurasiyası

QURAŞDIRMA:
1. Telegram-da @BotFather vasitəsilə bot yarat və token götür.
2. Bu üç faylı GitHub repozitoriyasına yüklə.
3. Render-də New + → Blueprint seçərək render.yaml faylını deploy et (və ya Web Service yaradıb build/start komandalarını yaz).
4. Render Environment bölməsində bunları əlavə et:
   BOT_TOKEN = BotFather tokeni
   DATABASE_URL = Render PostgreSQL Internal Database URL (əgər bağlantı alınmasa External URL istifadə et)
   ADMIN_IDS = sənin Telegram rəqəmsal user ID-n (bir neçə admin üçün vergüllə ayır)
   SUPPORT_USERNAME = ACE_SUPORT
5. Deploy et. Render loglarında “ACE PRIVÉ demo bot started” görünməlidir.

QEYD:
- BOT_TOKEN-i heç kimə göndərmə və GitHub-a kodun içinə yazma.
- ADMIN_IDS üçün @username yox, rəqəmsal Telegram ID yazılmalıdır.
- Render Free xidmətləri boş qalanda dayana/yuxuya gedə bilər; pulsuz planda 24/7 işləməyə zəmanət yoxdur.
- PostgreSQL bağlantısı və Render planının cari şərtləri Render panelində yoxlanmalıdır.

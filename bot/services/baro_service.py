import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.config import settings
from bot.database.models import User
from bot.services.audit_service import AuditService
from bot.services.rank_service import RankService
from bot.utils.time_utils import format_date_short_tr


class BaroVerificationService:
    """
    Avukat Baro Levha ve Sicil No Doğrulama Servisi
    (Tüm Türkiye Baroları, Sicil Doğrulama, Belge/Kimlik Onay Kuyruğu ve Rozet Yönetimi)
    """

    SUPPORTED_BAROLAR: List[str] = [
        "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Ankara 2 No'lu",
        "Antalya", "Artvin", "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu",
        "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne",
        "Elazığ", "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane",
        "Hakkari", "Hatay", "Isparta", "Mersin", "İstanbul", "İstanbul 2 No'lu", "İzmir",
        "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir", "Kocaeli", "Konya",
        "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla", "Muş",
        "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop",
        "Sivas", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak",
        "Van", "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman", "Kırıkkale",
        "Batman", "Şırnak", "Bartın", "Ardahan", "Iğdır", "Yalova", "Karabük",
        "Kilis", "Osmaniye", "Düzce"
    ]

    POPULAR_BAROLAR = [
        ["İstanbul", "Ankara", "İzmir"],
        ["Bursa", "Antalya", "Adana"],
        ["Konya", "Gaziantep", "Kocaeli"],
        ["İstanbul 2 No'lu", "Ankara 2 No'lu", "Diyarbakır"]
    ]

    @staticmethod
    def normalize_baro_name(input_str: str) -> Optional[str]:
        """Kullanıcının girdiği baro metnini 83 resmi baro adı ile akıllıca eşleştirir."""
        if not input_str:
            return None
        clean = input_str.strip().lower()
        clean = clean.replace("barosu", "").replace("baro", "").strip()

        # Özel kısaltma/numara eşleştirmeleri
        if clean in ["ist", "istanbul", "istanbul 1", "ist 1"]:
            return "İstanbul"
        if clean in ["ist 2", "istanbul 2", "istanbul 2 nolu", "istanbul 2 no'lu"]:
            return "İstanbul 2 No'lu"
        if clean in ["ank", "ankara", "ankara 1", "ank 1"]:
            return "Ankara"
        if clean in ["ank 2", "ankara 2", "ankara 2 nolu", "ankara 2 no'lu"]:
            return "Ankara 2 No'lu"
        if clean in ["izm", "izmir"]:
            return "İzmir"
        if clean in ["maras", "kahramanmaras", "k.maras"]:
            return "Kahramanmaraş"
        if clean in ["urfa", "sanliurfa"]:
            return "Şanlıurfa"
        if clean in ["ant", "antalya"]:
            return "Antalya"

        for b in BaroVerificationService.SUPPORTED_BAROLAR:
            if b.lower() == clean or clean in b.lower():
                return b

        return input_str.title().strip()

    @staticmethod
    def validate_sicil_format(sicil_no: str) -> bool:
        """Sicil numarasının sadece rakamlardan ve 3 ila 7 basamak uzunluğunda olduğunu doğrular."""
        if not sicil_no:
            return False
        clean = sicil_no.strip()
        return bool(re.match(r"^\d{3,7}$", clean))

    @staticmethod
    def get_baro_selection_keyboard() -> InlineKeyboardMarkup:
        """Kullanıcının hızlıca baro seçebileceği popüler baro butonları"""
        kb = []
        for row in BaroVerificationService.POPULAR_BAROLAR:
            btn_row = []
            for b in row:
                btn_row.append(InlineKeyboardButton(text=f"🏛️ {b}", callback_data=f"baro_sel:{b}"))
            kb.append(btn_row)

        kb.append([
            InlineKeyboardButton(text="✍️ Diğer Baroyu Kendim Yazacağım", callback_data="baro_sel:OTHER")
        ])
        kb.append([
            InlineKeyboardButton(text="❌ Vazgeç / İptal", callback_data="baro_sel:CANCEL")
        ])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    @staticmethod
    def get_admin_verification_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Adminlerin doğrulama talebini tek tıkla onaylayıp reddedebileceği butonlar"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Avukatlığı Onayla (+10 Puan)", callback_data=f"adm_act:approve_baro:{user_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Reddet (Belge Yetersiz)", callback_data=f"adm_act:reject_baro:{user_id}:belge"),
                InlineKeyboardButton(text="❌ Reddet (Hatalı Sicil)", callback_data=f"adm_act:reject_baro:{user_id}:sicil")
            ]
        ])

    @staticmethod
    async def submit_verification_request(
        bot: Bot,
        user_id: int,
        baro_name: str,
        sicil_no: str,
        tbb_sicil: Optional[str] = None,
        document_file_id: Optional[str] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """
        Kullanıcının baro doğrulama başvurusunu veritabanına kaydeder ve
        Admin Denetim Grubu'na anlık inceleme kartı gönderir.
        """
        norm_baro = BaroVerificationService.normalize_baro_name(baro_name)
        if not norm_baro:
            norm_baro = baro_name.strip()

        if not BaroVerificationService.validate_sicil_format(sicil_no):
            return {
                "success": False,
                "message": "⚠️ <b>Geçersiz Sicil Numarası:</b> Sicil no 3 ila 7 basamaklı rakamlardan oluşmalıdır."
            }

        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            return {"success": False, "message": "Kullanıcı kaydı bulunamadı."}

        user.baro_name = norm_baro
        user.baro_sicil_no = sicil_no.strip()
        if tbb_sicil:
            user.tbb_sicil_no = tbb_sicil.strip()
        user.baro_verification_status = "PENDING"
        if document_file_id:
            user.baro_document_file_id = document_file_id

        await db.commit()

        # Admin Denetim Grubuna Bildirim Gönder
        admin_text = (
            f"🎖️ <b>[YENİ AVUKAT / BARO DOĞRULAMA TALEBİ]</b>\n\n"
            f"👤 <b>Meslektaş:</b> {user.full_name}\n"
            f"📱 <b>Kullanıcı Adı:</b> @{user.username or 'yok'}\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.id}</code>\n"
            f"🏛️ <b>Kayıtlı Baro:</b> <b>{norm_baro} Barosu</b>\n"
            f"🔢 <b>Baro Sicil No:</b> <code>{sicil_no}</code>\n"
            f"🌐 <b>TBB Sicil No:</b> <code>{user.tbb_sicil_no or 'Belirtilmedi'}</code>\n"
            f"⭐ <b>Mevcut Rank Skoru:</b> ⭐ {user.rank_score} (Ceza: {user.penalty_points})\n"
            f"📅 <b>Başvuru Zamanı:</b> {datetime.utcnow().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<i>Lütfen TBB Levha / Baro Sorgu ekranından sicili kontrol edip onaylayınız veya reddediniz:</i>"
        )
        kb = BaroVerificationService.get_admin_verification_keyboard(user.id)

        try:
            if document_file_id:
                # Belge veya Kimlik Fotoğrafı Ekiyle Gönder
                try:
                    await bot.send_photo(
                        chat_id=settings.admin_chat_id,
                        photo=document_file_id,
                        caption=admin_text[:1024],
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                except Exception:
                    await bot.send_document(
                        chat_id=settings.admin_chat_id,
                        document=document_file_id,
                        caption=admin_text[:1024],
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            else:
                await bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=admin_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"[BaroService] Admin grubuna doğrulama talebi gönderilemedi: {e}")

        return {
            "success": True,
            "message": (
                f"✅ <b>Baro Levha Doğrulama Talebiniz Alındı!</b>\n\n"
                f"🏛️ <b>Baro:</b> {norm_baro} Barosu\n"
                f"🔢 <b>Sicil No:</b> {sicil_no}\n"
                f"📌 <b>Durum:</b> ⏳ <i>Yönetici Onayı Bekleniyor...</i>\n\n"
                f"Bilgileriniz TBB Levha / Baro sorgusu üzerinden denetlendikten sonra "
                f"profilinize <b>🎖️ 'Baro Onaylı Avukat'</b> rozeti ve <b>+10 Rank Puanı</b> tanımlanacaktır."
            )
        }

    @staticmethod
    async def approve_verification(
        bot: Bot,
        user_id: int,
        admin_name: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Admin tarafından doğrulamayı onaylar, +10 puan verir ve kullanıcıya DM gönderir."""
        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            return {"success": False, "message": "Kullanıcı bulunamadı."}

        now = datetime.utcnow()
        user.is_baro_verified = True
        user.baro_verification_status = "VERIFIED"
        user.baro_verified_at = now
        user.rank_score += 10  # Onaylı Avukat Bonusu

        await db.commit()

        # Kullanıcıya DM Tebligatı
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 <b>Tebrikler Sayın Av. {user.full_name}!</b>\n\n"
                    f"🏛️ <b>{user.baro_name} Barosu ({user.baro_sicil_no})</b> levha kaydınız yöneticilerimiz tarafından başarıyla doğrulanmıştır.\n\n"
                    f"🎖️ <b>Kazanılan Haklar ve Rozetler:</b>\n"
                    f"• <b>Grupta Mesaj Gönderme İzniniz Açıldı ✅</b>\n"
                    f"• Profilinize <b>'Baro Onaylı Avukat'</b> rozeti eklendi.\n"
                    f"• Hesabınıza <b>+10 Güven / Rank Puanı</b> tanımlandı.\n"
                    f"• Tevkil panolarında başvurularınız artık <b>onaylı meslektaş</b> olarak öncelikli görünecektir.\n\n"
                    f"Başarılı tevkil ve iyi çalışmalar dileriz."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BaroService] Kullanıcıya onay DM'si gönderilemedi: {e}")

        # Gruplardaki mesaj kısıtlamasını kaldır
        try:
            from bot.database.models import Listing
            from aiogram.types import ChatPermissions
            grp_stmt = select(Listing.group_id).where(Listing.group_id.isnot(None)).distinct()
            res_grp = await db.execute(grp_stmt)
            for row in res_grp.fetchall():
                gid = row[0]
                if gid and gid != settings.admin_chat_id:
                    try:
                        await bot.restrict_chat_member(
                            chat_id=gid,
                            user_id=user_id,
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True
                            )
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "success": True,
            "message": f"✅ {user.full_name} ({user_id}) avukatlığı başarıyla onaylandı ve +10 puan eklendi.",
            "user": user
        }

    @staticmethod
    async def reject_verification(
        bot: Bot,
        user_id: int,
        reason_code: str,
        admin_name: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Admin tarafından doğrulamayı reddeder ve kullanıcıya DM ile bilgi verir."""
        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            return {"success": False, "message": "Kullanıcı bulunamadı."}

        reasons = {
            "belge": "Yüklenen kimlik/ruhsat belgesi okunamadı veya teyit edilemedi.",
            "sicil": "Girilen baro ve sicil numarası TBB Levha kayıtlarıyla uyuşmuyor.",
            "diger": "Yöneticilerimiz tarafından doğrulama kriterlerini karşılamadığı belirlendi."
        }
        reason_text = reasons.get(reason_code, reason_code)

        user.is_baro_verified = False
        user.baro_verification_status = "REJECTED"
        await db.commit()

        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"ℹ️ <b>Baro Doğrulama Talebiniz Hakkında</b>\n\n"
                    f"Sayın {user.full_name}, baro levha doğrulama başvurunuz aşağıdaki gerekçe ile onaylanamamıştır:\n\n"
                    f"📌 <b>Gerekçe:</b> <i>{reason_text}</i>\n\n"
                    f"Bilgilerinizi veya belgenizi kontrol ederek botumuz üzerinden <code>/baro_dogrula</code> "
                    f"komutu ile dilediğiniz zaman yeniden başvurabilirsiniz."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BaroService] Kullanıcıya red DM'si iletilemedi: {e}")

        return {
            "success": True,
            "message": f"❌ {user.full_name} ({user_id}) doğrulama talebi reddedildi ({reason_text}).",
            "user": user
        }

    @staticmethod
    async def verify_lawyer_credentials(
        user_id: int,
        baro_name: str,
        sicil_no: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Geriye dönük uyumluluk için hızlı doğrulamayı destekler."""
        norm_baro = BaroVerificationService.normalize_baro_name(baro_name) or baro_name.strip()
        if not BaroVerificationService.validate_sicil_format(sicil_no):
            return {
                "success": False,
                "message": "⚠️ Geçersiz sicil numarası formatı. Sicil no 3 ila 7 basamaklı rakamlardan oluşmalıdır."
            }

        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            return {"success": False, "message": "Kullanıcı bulunamadı."}

        user.baro_name = norm_baro
        user.baro_sicil_no = sicil_no.strip()
        user.is_baro_verified = True
        user.baro_verification_status = "VERIFIED"
        user.baro_verified_at = datetime.utcnow()
        await db.commit()

        return {
            "success": True,
            "message": f"✅ <b>{norm_baro} Barosu</b> ({sicil_no}) sicil no ile avukatlık kaydınız sisteme başarıyla tanımlandı.",
            "baro_name": user.baro_name,
            "sicil_no": user.baro_sicil_no
        }

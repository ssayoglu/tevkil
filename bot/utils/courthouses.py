from typing import Set

# Türkiye'de Adliyesi / Mülhakatı Bulunan Tüm İl, İlçe ve Adliye Merkezleri
TURKISH_COURTHOUSES: Set[str] = {
    # 81 İl
    "adana", "adiyaman", "afyonkarahisar", "afyon", "agri", "aksaray", "amasya", "ankara", "antalya",
    "ardahan", "artvin", "aydin", "balikesir", "bartin", "batman", "bayburt", "bilecik", "bingol",
    "bitlis", "bolu", "burdur", "bursa", "canakkale", "cankiri", "corum", "denizli", "diyarbakir",
    "duzce", "edirne", "elazig", "erzincan", "erzurum", "eskisehir", "gaziantep", "giresun", "gumushane",
    "hakkari", "hatay", "igdir", "isparta", "istanbul", "izmir", "kahramanmaras", "maras", "karabuk",
    "karaman", "kars", "kastamonu", "kayseri", "kirikkale", "kirklareli", "kirsehir", "kilis", "kocaeli",
    "konya", "kutahya", "malatya", "manisa", "mardin", "mersin", "icel", "mugla", "mus", "nevsehir",
    "nigde", "ordu", "osmaniye", "rize", "sakarya", "adapazari", "samsun", "siirt", "sinop", "sivas",
    "sanliurfa", "urfa", "sirnak", "tekirdag", "tokat", "trabzon", "tunceli", "usak", "van", "yozgat", "zonguldak",

    # İstanbul Adliyeleri & İlçeleri
    "caglayan", "kartal", "anadolu", "bakirkoy", "gaziosmanpasa", "gop", "silivri", "catalca",
    "buyukcekmece", "kucukcekmece", "beykoz", "sile", "adalar", "avcilar", "bagcilar", "bahcelievler",
    "basaksehir", "bayrampasa", "besiktas", "beylikduzu", "beyoglu", "esenler", "esenyurt", "eyup",
    "eyupsultan", "fatih", "kadikoy", "kagithane", "maltepe", "pendik", "sancaktepe", "sariyer",
    "sultanbeyli", "sultangazi", "tuzla", "umraniye", "uskudar", "zeytinburnu",

    # Ankara Adliyeleri & İlçeleri
    "sihhiye", "sofutler", "batipark", "yenimahalle", "cankaya", "kecioren", "mamak", "sincan", "etimesgut",
    "golbasi", "cubuk", "polatli", "beypazari", "elmadag", "kahramankazan", "kazan", "nallihan",
    "haymana", "kizilcahamam", "bala", "ayas", "kalecik", "camlidere", "gudul", "evren", "sereflikochisar",

    # İzmir Adliyeleri & İlçeleri
    "bayrakli", "karsiyaka", "bornova", "buca", "konak", "karabaglar", "cigli", "gaziemir",
    "menemen", "torbali", "odemis", "kemalpasa", "bergama", "aliaga", "menderes", "tire",
    "cesme", "urla", "seferihisar", "selcuk", "dikili", "foca", "kinik", "karaburun", "kiraz", "beydag",

    # Bursa İlçeleri
    "osmangazi", "yildirim", "nilufer", "inegol", "gemlik", "mustafakemalpasa", "mudanya",
    "orhangazi", "yenisehir", "iznik", "karacabey", "keles", "orhaneli", "buyukorhan", "harmancik",

    # Çanakkale İlçeleri
    "bayramic", "biga", "can", "gelibolu", "ezine", "ayvacik", "yenice", "lapseki", "eceabat",
    "gokceada", "bozcaada",

    # Balıkesir İlçeleri
    "bandirma", "edremit", "ayvalik", "burhaniye", "gonen", "erdek", "susurluk", "dursunbey",
    "bigadic", "sindirgi", "ivrindi", "havran", "manyas", "kepsut", "savastepe", "marmara", "balya", "gomec",

    # Muğla İlçeleri
    "bodrum", "fethiye", "marmaris", "milas", "ortaca", "dalaman", "koycegiz", "yatagan",
    "datca", "ula", "seydikemer", "kavaklidere",

    # Antalya İlçeleri
    "alanya", "manavgat", "serik", "kemer", "elmali", "kumluca", "kas", "akseki", "korkuteli",
    "gazipasa", "finike", "demre", "kale", "ibradi", "gundogmus",

    # Aydın İlçeleri
    "kusadasi", "soke", "nazilli", "didim", "cine", "germencik", "incirliova", "bozdogan",
    "kocarli", "kuyucak", "karacasu", "buharkent", "yenipazar", "sultanhisar", "kosk",

    # Tekirdağ İlçeleri
    "corlu", "cerkezkoy", "kapakli", "suleymanpasa", "saray", "malkara", "hayrabolu",
    "muratli", "sarkoy", "marmaraereglisi", "ergene",

    # Kocaeli İlçeleri
    "gebze", "izmit", "darica", "korfez", "golcuk", "derince", "cayirova", "kartepe",
    "basiskele", "karamursel", "kandira", "dilovasi",

    # Manisa İlçeleri
    "akhisar", "salihli", "turgutlu", "alasehir", "soma", "kirkagac", "sarigol", "kula",
    "demirci", "gordes", "saruhanli", "selendi", "ahmetli", "koprubasi",

    # Adana & Mersin İlçeleri
    "seyhan", "yuregir", "cukurova", "saricam", "ceyhan", "kozan", "imamoglu", "karatas",
    "karaisali", "pozanti", "feke", "yumurtalik", "tufanbeyli", "aladag", "saimbeyli",
    "tarsus", "toroslar", "akdeniz", "yenisehir", "mezitli", "erdemli", "silifke", "anamur",
    "mut", "gulnar", "aydincik", "bozyazi", "camliyayla",

    # Hatay & Gaziantep İlçeleri
    "antakya", "iskenderun", "defne", "dortyol", "samandag", "kirikhan", "re बयानli", "reyhanli",
    "arsuz", "altinozu", "hassa", "erzin", "payas", "belen", "yayladagi", "kumlu",
    "sahinbey", "sehitkamil", "nizip", "islahiye", "nurdagi", "araban", "oguzeli", "yavuzeli", "karkamis",

    # Konya İlçeleri
    "selcuklu", "meram", "karatay", "eregli", "aksehir", "beysehir", "seydisehir", "cihanbeyli",
    "kulu", "ilgin", "cumra", "karapinar", "kadinhani", "sarayonu", "bozkir", "yunak", "huyuk",
    "doganhisar", "hadim", "celtik", "guneysinir", "taskent", "tuzlukcu", "derebucak", "yalihuyuk",

    # Samsun, Ordu, Trabzon, Rize, Giresun İlçeleri
    "ilkadim", "atakum", "canik", "bafra", "carsamba", "terme", "vezirkopru", "havza", "alacam",
    "ondokuzmayis", "19 mayis", "tekkekoy", "kavak", "salipazari", "ayvacik", "ladik", "yakakent",
    "altinordu", "unye", "fatsa", "kumru", "korgan", "golköy", "persembe", "aybasti",
    "ortahisar", "akcaabat", "arakli", "of", "yomra", "arsin", "vakfikebir", "surmene", "macka",
    "besikduzu", "caykara", "tonya", "duzkoy", "salpazari", "carsibasi", "dernekpazari",
    "merkez", "cayeli", "ardesen", "pazar", "findikli", "guneysu", "kalkandere", "iyidere", "derepazari", "camlihemsin", "ikizdere",
    "bulancak", "espiye", "gorele", "tirebolu", "dereli", "sebinkarahisar", "yaglidere", "kesap", "piraziz", "eynesil", "alucra", "camoluk",

    # Şanlıurfa & Diyarbakır & Mardin İlçeleri
    "eyyubiye", "haliliye", "karakopru", "siverek", "virangil", "viransehir", "birecik", "suruc",
    "ceylanpinar", "akcakale", "hilvan", "bozova", "harran", "halfeti",
    "baglar", "kayapinar", "yenisehir", "sur", "ergani", "bismil", "silvan", "cinar", "cermik", "dicle", "kulp", "hani", "lice", "egil", "hazro", "kocakoy", "cungus",
    "artuklu", "kiziltepe", "midyat", "nusaybin", "derik", "mazidagi", "dargecit", "savur", "yesilli", "omerli",

    # Sakarya, Düzce, Bolu, Zonguldak İlçeleri
    "serdivan", "adapazari", "akyazi", "erenler", "hendek", "karasu", "geyve", "arifiye", "sapanca", "pamukova", "ferizli", "kocaali", "kaynarca", "sogutlu", "tarakli",
    "akcakoca", "kaynasli", "golyaka", "cilimli", "gumusova", "cumayeri", "yigilca",
    "gerede", "mengeni", "mengen", "mudurnu", "goynuk", "seben", "dortdivan", "yenicaga", "kibriscik",
    "kdz eregli", "eregli", "caycuma", "devrek", "kozlu", "kilimli", "alapli", "gokcebey",

    # Diğer Önemli Adliye İlçeleri
    "turgutlu", "erbaa", "niksar", "turhal", "zile", "alasehir", "akhisar", "boyabat", "sorgun",
    "ercis", "cizre", "silopi", "midyat", "siverek", "elbistan", "afsin", "pazarcik", "turkoglu",
    "meram", "selcuklu", "sungurlu", "osmancik", "iskilip", "alaca", "bayat", "kargi",
    "bozyazi", "polatli", "sereflikochisar", "beypazari", "nallihan", "tavsanli", "simav", "gediz", "emet",
    "dinar", "bolvadin", "sandikli", "emirdag", "cay", "suhut", "hocalar", "isaniyeli", "ihsaniye"
}


def normalize_text_for_search(text: str) -> str:
    """Türkçe karakterleri ve noktalama işaretlerini arama için normalize eder."""
    if not text:
        return ""
    return (
        text.replace("İ", "i")
        .replace("I", "ı")
        .lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )

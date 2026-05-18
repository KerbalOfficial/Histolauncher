const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', 'src', 'ui', 'i18n');
const en = JSON.parse(fs.readFileSync(path.join(root, 'en.json'), 'utf8'));

const translations = {
  ar: {
    skinEditor: {
      textureType: 'نوع الملمس', textureDefault: 'افتراضي', textureLegacy: 'قديم', armMirror: 'عكس الذراع', legMirror: 'عكس الساق', mirrorRight: 'يمين', mirrorLeft: 'يسار', overlayToFirstLayer: 'دمج الطبقة العلوية مع الطبقة الأولى', overlayHead: 'الرأس', overlayBody: 'السترة', overlayRightArm: 'الكم الأيمن', overlayLeftArm: 'الكم الأيسر', overlayRightLeg: 'الساق اليمنى', overlayLeftLeg: 'الساق اليسرى'
    },
    mods: { dependencies: { title: 'تبعيات التعديل', checking: 'جار فحص التبعيات...', prompt: 'يحتاج هذا التعديل إلى تبعيات ليعمل بشكل صحيح. اختر التبعيات التي تريد تثبيتها:', installSelected: 'تثبيت المحدد', installing: 'جار تثبيت التبعيات...', required: 'مطلوب' } },
  },
  de: {
    skinEditor: {
      textureType: 'Texturtyp', textureDefault: 'Standard', textureLegacy: 'Klassisch', armMirror: 'Arme spiegeln', legMirror: 'Beine spiegeln', mirrorRight: 'Rechts', mirrorLeft: 'Links', overlayToFirstLayer: 'Überlagerung auf erste Ebene anwenden', overlayHead: 'Kopf', overlayBody: 'Jacke', overlayRightArm: 'Rechter Ärmel', overlayLeftArm: 'Linker Ärmel', overlayRightLeg: 'Rechtes Hosenbein', overlayLeftLeg: 'Linkes Hosenbein'
    },
    mods: { dependencies: { title: 'Mod-Abhängigkeiten', checking: 'Abhängigkeiten werden geprüft...', prompt: 'Diese Mod benötigt Abhängigkeiten, um richtig zu funktionieren. Wähle aus, welche Abhängigkeiten installiert werden sollen:', installSelected: 'Ausgewählte installieren', installing: 'Abhängigkeiten werden installiert...', required: 'Erforderlich' } },
  },
  es: {
    skinEditor: {
      textureType: 'Tipo de textura', textureDefault: 'Predeterminada', textureLegacy: 'Clásica', armMirror: 'Reflejo de brazos', legMirror: 'Reflejo de piernas', mirrorRight: 'Derecha', mirrorLeft: 'Izquierda', overlayToFirstLayer: 'Aplicar capa exterior a la primera capa', overlayHead: 'Cabeza', overlayBody: 'Chaqueta', overlayRightArm: 'Manga derecha', overlayLeftArm: 'Manga izquierda', overlayRightLeg: 'Pantalón derecho', overlayLeftLeg: 'Pantalón izquierdo'
    },
    mods: { dependencies: { title: 'Dependencias del mod', checking: 'Comprobando dependencias...', prompt: 'Este mod necesita dependencias para funcionar correctamente. Elige cuáles quieres instalar:', installSelected: 'Instalar seleccionadas', installing: 'Instalando dependencias...', required: 'Obligatoria' } },
  },
  fr: {
    skinEditor: {
      textureType: 'Type de texture', textureDefault: 'Par défaut', textureLegacy: 'Classique', armMirror: 'Miroir des bras', legMirror: 'Miroir des jambes', mirrorRight: 'Droite', mirrorLeft: 'Gauche', overlayToFirstLayer: 'Appliquer la surcouche à la première couche', overlayHead: 'Tête', overlayBody: 'Veste', overlayRightArm: 'Manche droite', overlayLeftArm: 'Manche gauche', overlayRightLeg: 'Jambe droite', overlayLeftLeg: 'Jambe gauche'
    },
    mods: { dependencies: { title: 'Dépendances du mod', checking: 'Vérification des dépendances...', prompt: 'Ce mod a besoin de dépendances pour fonctionner correctement. Choisis celles que tu veux installer :', installSelected: 'Installer la sélection', installing: 'Installation des dépendances...', required: 'Requise' } },
  },
  he: {
    skinEditor: {
      textureType: 'סוג טקסטורה', textureDefault: 'ברירת מחדל', textureLegacy: 'ישן', armMirror: 'שיקוף ידיים', legMirror: 'שיקוף רגליים', mirrorRight: 'ימין', mirrorLeft: 'שמאל', overlayToFirstLayer: 'העברת שכבת על לשכבה הראשונה', overlayHead: 'ראש', overlayBody: 'מעיל', overlayRightArm: 'שרוול ימין', overlayLeftArm: 'שרוול שמאל', overlayRightLeg: 'מכנס ימין', overlayLeftLeg: 'מכנס שמאל'
    },
    mods: { dependencies: { title: 'תלויות המוד', checking: 'בודק תלויות...', prompt: 'המוד הזה צריך תלויות כדי לעבוד כראוי. בחר אילו תלויות להתקין:', installSelected: 'התקן נבחרים', installing: 'מתקין תלויות...', required: 'נדרש' } },
  },
  hu: {
    skinEditor: {
      textureType: 'Textúratípus', textureDefault: 'Alapértelmezett', textureLegacy: 'Régi', armMirror: 'Kar tükrözése', legMirror: 'Láb tükrözése', mirrorRight: 'Jobb', mirrorLeft: 'Bal', overlayToFirstLayer: 'Fedőréteg az első rétegre', overlayHead: 'Fej', overlayBody: 'Kabát', overlayRightArm: 'Jobb ujj', overlayLeftArm: 'Bal ujj', overlayRightLeg: 'Jobb nadrágszár', overlayLeftLeg: 'Bal nadrágszár'
    },
    mods: { dependencies: { title: 'Modfüggőségek', checking: 'Függőségek ellenőrzése...', prompt: 'Ennek a modnak függőségekre van szüksége a megfelelő működéshez. Válaszd ki, melyeket szeretnéd telepíteni:', installSelected: 'Kijelöltek telepítése', installing: 'Függőségek telepítése...', required: 'Kötelező' } },
  },
  id: {
    skinEditor: {
      textureType: 'Jenis tekstur', textureDefault: 'Default', textureLegacy: 'Legacy', armMirror: 'Cermin lengan', legMirror: 'Cermin kaki', mirrorRight: 'Kanan', mirrorLeft: 'Kiri', overlayToFirstLayer: 'Terapkan overlay ke lapisan pertama', overlayHead: 'Kepala', overlayBody: 'Jaket', overlayRightArm: 'Lengan kanan', overlayLeftArm: 'Lengan kiri', overlayRightLeg: 'Celana kanan', overlayLeftLeg: 'Celana kiri'
    },
    mods: { dependencies: { title: 'Dependensi mod', checking: 'Memeriksa dependensi...', prompt: 'Mod ini membutuhkan dependensi agar berfungsi dengan benar. Pilih dependensi yang ingin dipasang:', installSelected: 'Pasang yang dipilih', installing: 'Memasang dependensi...', required: 'Wajib' } },
  },
  it: {
    skinEditor: {
      textureType: 'Tipo di texture', textureDefault: 'Predefinita', textureLegacy: 'Classica', armMirror: 'Specchia braccia', legMirror: 'Specchia gambe', mirrorRight: 'Destra', mirrorLeft: 'Sinistra', overlayToFirstLayer: 'Applica overlay al primo livello', overlayHead: 'Testa', overlayBody: 'Giacca', overlayRightArm: 'Manica destra', overlayLeftArm: 'Manica sinistra', overlayRightLeg: 'Pantalone destro', overlayLeftLeg: 'Pantalone sinistro'
    },
    mods: { dependencies: { title: 'Dipendenze della mod', checking: 'Controllo dipendenze...', prompt: 'Questa mod richiede dipendenze per funzionare correttamente. Scegli quali vuoi installare:', installSelected: 'Installa selezionate', installing: 'Installazione dipendenze...', required: 'Richiesta' } },
  },
  ja: {
    skinEditor: {
      textureType: 'テクスチャタイプ', textureDefault: 'デフォルト', textureLegacy: 'レガシー', armMirror: '腕のミラー', legMirror: '脚のミラー', mirrorRight: '右', mirrorLeft: '左', overlayToFirstLayer: 'オーバーレイを第一レイヤーへ', overlayHead: '頭', overlayBody: 'ジャケット', overlayRightArm: '右袖', overlayLeftArm: '左袖', overlayRightLeg: '右ズボン', overlayLeftLeg: '左ズボン'
    },
    mods: { dependencies: { title: 'Mod の依存関係', checking: '依存関係を確認中...', prompt: 'この Mod が正しく動作するには依存関係が必要です。インストールする依存関係を選択してください:', installSelected: '選択したものをインストール', installing: '依存関係をインストール中...', required: '必須' } },
  },
  ko: {
    skinEditor: {
      textureType: '텍스처 유형', textureDefault: '기본', textureLegacy: '레거시', armMirror: '팔 미러', legMirror: '다리 미러', mirrorRight: '오른쪽', mirrorLeft: '왼쪽', overlayToFirstLayer: '오버레이를 첫 번째 레이어로 적용', overlayHead: '머리', overlayBody: '재킷', overlayRightArm: '오른쪽 소매', overlayLeftArm: '왼쪽 소매', overlayRightLeg: '오른쪽 바지', overlayLeftLeg: '왼쪽 바지'
    },
    mods: { dependencies: { title: '모드 의존성', checking: '의존성 확인 중...', prompt: '이 모드가 제대로 작동하려면 의존성이 필요합니다. 설치할 의존성을 선택하세요:', installSelected: '선택 항목 설치', installing: '의존성 설치 중...', required: '필수' } },
  },
  nl: {
    skinEditor: {
      textureType: 'Textuurtype', textureDefault: 'Standaard', textureLegacy: 'Legacy', armMirror: 'Armen spiegelen', legMirror: 'Benen spiegelen', mirrorRight: 'Rechts', mirrorLeft: 'Links', overlayToFirstLayer: 'Overlay op eerste laag toepassen', overlayHead: 'Hoofd', overlayBody: 'Jas', overlayRightArm: 'Rechtermouw', overlayLeftArm: 'Linkermouw', overlayRightLeg: 'Rechter broekspijp', overlayLeftLeg: 'Linker broekspijp'
    },
    mods: { dependencies: { title: 'Mod-afhankelijkheden', checking: 'Afhankelijkheden controleren...', prompt: 'Deze mod heeft afhankelijkheden nodig om goed te werken. Kies welke je wilt installeren:', installSelected: 'Geselecteerde installeren', installing: 'Afhankelijkheden installeren...', required: 'Vereist' } },
  },
  pl: {
    skinEditor: {
      textureType: 'Typ tekstury', textureDefault: 'Domyślna', textureLegacy: 'Klasyczna', armMirror: 'Odbicie rąk', legMirror: 'Odbicie nóg', mirrorRight: 'Prawa', mirrorLeft: 'Lewa', overlayToFirstLayer: 'Nałóż warstwę zewnętrzną na pierwszą', overlayHead: 'Głowa', overlayBody: 'Kurtka', overlayRightArm: 'Prawy rękaw', overlayLeftArm: 'Lewy rękaw', overlayRightLeg: 'Prawa nogawka', overlayLeftLeg: 'Lewa nogawka'
    },
    mods: { dependencies: { title: 'Zależności moda', checking: 'Sprawdzanie zależności...', prompt: 'Ten mod wymaga zależności do poprawnego działania. Wybierz, które chcesz zainstalować:', installSelected: 'Zainstaluj wybrane', installing: 'Instalowanie zależności...', required: 'Wymagane' } },
  },
  'pt-br': {
    skinEditor: {
      textureType: 'Tipo de textura', textureDefault: 'Padrão', textureLegacy: 'Clássica', armMirror: 'Espelhar braços', legMirror: 'Espelhar pernas', mirrorRight: 'Direita', mirrorLeft: 'Esquerda', overlayToFirstLayer: 'Aplicar sobreposição à primeira camada', overlayHead: 'Cabeça', overlayBody: 'Jaqueta', overlayRightArm: 'Manga direita', overlayLeftArm: 'Manga esquerda', overlayRightLeg: 'Calça direita', overlayLeftLeg: 'Calça esquerda'
    },
    mods: { dependencies: { title: 'Dependências do mod', checking: 'Verificando dependências...', prompt: 'Este mod precisa de dependências para funcionar corretamente. Escolha quais deseja instalar:', installSelected: 'Instalar selecionadas', installing: 'Instalando dependências...', required: 'Obrigatória' } },
  },
  ro: {
    skinEditor: {
      textureType: 'Tip textură', textureDefault: 'Implicită', textureLegacy: 'Clasică', armMirror: 'Oglindire brațe', legMirror: 'Oglindire picioare', mirrorRight: 'Dreapta', mirrorLeft: 'Stânga', overlayToFirstLayer: 'Aplică stratul exterior pe primul strat', overlayHead: 'Cap', overlayBody: 'Jachetă', overlayRightArm: 'Mânecă dreaptă', overlayLeftArm: 'Mânecă stângă', overlayRightLeg: 'Pantalon drept', overlayLeftLeg: 'Pantalon stâng'
    },
    mods: { dependencies: { title: 'Dependințe mod', checking: 'Se verifică dependințele...', prompt: 'Acest mod are nevoie de dependințe pentru a funcționa corect. Alege ce dependințe vrei să instalezi:', installSelected: 'Instalează selectate', installing: 'Se instalează dependințele...', required: 'Necesară' } },
  },
  ru: {
    skinEditor: {
      textureType: 'Тип текстуры', textureDefault: 'По умолчанию', textureLegacy: 'Классическая', armMirror: 'Зеркалирование рук', legMirror: 'Зеркалирование ног', mirrorRight: 'Правая', mirrorLeft: 'Левая', overlayToFirstLayer: 'Наложить внешний слой на первый слой', overlayHead: 'Голова', overlayBody: 'Куртка', overlayRightArm: 'Правый рукав', overlayLeftArm: 'Левый рукав', overlayRightLeg: 'Правая штанина', overlayLeftLeg: 'Левая штанина'
    },
    mods: { dependencies: { title: 'Зависимости мода', checking: 'Проверка зависимостей...', prompt: 'Этому моду нужны зависимости для правильной работы. Выберите, какие зависимости установить:', installSelected: 'Установить выбранные', installing: 'Установка зависимостей...', required: 'Обязательно' } },
  },
  sv: {
    skinEditor: {
      textureType: 'Texturtyp', textureDefault: 'Standard', textureLegacy: 'Klassisk', armMirror: 'Spegla armar', legMirror: 'Spegla ben', mirrorRight: 'Höger', mirrorLeft: 'Vänster', overlayToFirstLayer: 'Applicera överlager på första lagret', overlayHead: 'Huvud', overlayBody: 'Jacka', overlayRightArm: 'Höger ärm', overlayLeftArm: 'Vänster ärm', overlayRightLeg: 'Höger byxben', overlayLeftLeg: 'Vänster byxben'
    },
    mods: { dependencies: { title: 'Modberoenden', checking: 'Kontrollerar beroenden...', prompt: 'Den här modden behöver beroenden för att fungera korrekt. Välj vilka beroenden du vill installera:', installSelected: 'Installera valda', installing: 'Installerar beroenden...', required: 'Krävs' } },
  },
  tr: {
    skinEditor: {
      textureType: 'Doku türü', textureDefault: 'Varsayılan', textureLegacy: 'Eski', armMirror: 'Kol aynalama', legMirror: 'Bacak aynalama', mirrorRight: 'Sağ', mirrorLeft: 'Sol', overlayToFirstLayer: 'Üst katmanı ilk katmana uygula', overlayHead: 'Baş', overlayBody: 'Ceket', overlayRightArm: 'Sağ kol', overlayLeftArm: 'Sol kol', overlayRightLeg: 'Sağ pantolon', overlayLeftLeg: 'Sol pantolon'
    },
    mods: { dependencies: { title: 'Mod bağımlılıkları', checking: 'Bağımlılıklar kontrol ediliyor...', prompt: 'Bu modun düzgün çalışması için bağımlılıklara ihtiyacı var. Yüklemek istediklerini seç:', installSelected: 'Seçilenleri yükle', installing: 'Bağımlılıklar yükleniyor...', required: 'Gerekli' } },
  },
  uk: {
    skinEditor: {
      textureType: 'Тип текстури', textureDefault: 'Стандартна', textureLegacy: 'Класична', armMirror: 'Дзеркалення рук', legMirror: 'Дзеркалення ніг', mirrorRight: 'Права', mirrorLeft: 'Ліва', overlayToFirstLayer: 'Накласти верхній шар на перший шар', overlayHead: 'Голова', overlayBody: 'Куртка', overlayRightArm: 'Правий рукав', overlayLeftArm: 'Лівий рукав', overlayRightLeg: 'Права штанина', overlayLeftLeg: 'Ліва штанина'
    },
    mods: { dependencies: { title: 'Залежності мода', checking: 'Перевірка залежностей...', prompt: 'Цьому моду потрібні залежності для правильної роботи. Виберіть, які залежності встановити:', installSelected: 'Встановити вибрані', installing: 'Встановлення залежностей...', required: 'Обов’язково' } },
  },
  vi: {
    skinEditor: {
      textureType: 'Loại kết cấu', textureDefault: 'Mặc định', textureLegacy: 'Cũ', armMirror: 'Đối xứng tay', legMirror: 'Đối xứng chân', mirrorRight: 'Phải', mirrorLeft: 'Trái', overlayToFirstLayer: 'Áp dụng lớp phủ vào lớp đầu tiên', overlayHead: 'Đầu', overlayBody: 'Áo khoác', overlayRightArm: 'Tay áo phải', overlayLeftArm: 'Tay áo trái', overlayRightLeg: 'Ống quần phải', overlayLeftLeg: 'Ống quần trái'
    },
    mods: { dependencies: { title: 'Phụ thuộc của mod', checking: 'Đang kiểm tra phụ thuộc...', prompt: 'Mod này cần các phụ thuộc để hoạt động đúng. Chọn phụ thuộc bạn muốn cài đặt:', installSelected: 'Cài đặt mục đã chọn', installing: 'Đang cài đặt phụ thuộc...', required: 'Bắt buộc' } },
  },
  'zh-cn': {
    skinEditor: {
      textureType: '纹理类型', textureDefault: '默认', textureLegacy: '旧版', armMirror: '手臂镜像', legMirror: '腿部镜像', mirrorRight: '右', mirrorLeft: '左', overlayToFirstLayer: '将外层应用到第一层', overlayHead: '头部', overlayBody: '外套', overlayRightArm: '右袖', overlayLeftArm: '左袖', overlayRightLeg: '右裤腿', overlayLeftLeg: '左裤腿'
    },
    mods: { dependencies: { title: '模组依赖', checking: '正在检查依赖...', prompt: '此模组需要依赖项才能正常工作。请选择要安装的依赖项：', installSelected: '安装所选项', installing: '正在安装依赖...', required: '必需' } },
  },
  'zh-tw': {
    skinEditor: {
      textureType: '紋理類型', textureDefault: '預設', textureLegacy: '舊版', armMirror: '手臂鏡像', legMirror: '腿部鏡像', mirrorRight: '右', mirrorLeft: '左', overlayToFirstLayer: '將外層套用到第一層', overlayHead: '頭部', overlayBody: '外套', overlayRightArm: '右袖', overlayLeftArm: '左袖', overlayRightLeg: '右褲管', overlayLeftLeg: '左褲管'
    },
    mods: { dependencies: { title: '模組相依項', checking: '正在檢查相依項...', prompt: '此模組需要相依項才能正常運作。請選擇要安裝的相依項：', installSelected: '安裝所選項目', installing: '正在安裝相依項...', required: '必要' } },
  },
};

const getPath = (obj, pathParts) => pathParts.reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
const setPath = (obj, pathParts, value) => {
  let cursor = obj;
  for (let index = 0; index < pathParts.length - 1; index += 1) {
    const key = pathParts[index];
    if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
    cursor = cursor[key];
  }
  cursor[pathParts[pathParts.length - 1]] = value;
};

let changedFiles = 0;
for (const [locale, sections] of Object.entries(translations)) {
  const file = path.join(root, `${locale}.json`);
  if (!fs.existsSync(file)) continue;
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  let changed = false;

  const applySection = (prefix, entries) => {
    for (const [key, value] of Object.entries(entries)) {
      const parts = [...prefix, key];
      const current = getPath(data, parts);
      const english = getPath(en, parts);
      if (current === undefined || current === english) {
        setPath(data, parts, value);
        changed = true;
      }
    }
  };

  if (sections.skinEditor) applySection(['skinEditor'], sections.skinEditor);
  if (sections.mods && sections.mods.dependencies) applySection(['mods', 'dependencies'], sections.mods.dependencies);

  if (changed) {
    fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
    changedFiles += 1;
  }
}

console.log(`Updated ${changedFiles} locale files.`);

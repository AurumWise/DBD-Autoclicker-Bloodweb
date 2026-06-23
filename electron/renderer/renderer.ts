type BloodwebApi = {
  command<T = BotState>(command: string, payload?: Record<string, unknown>): Promise<T>;
  setAlwaysOnTop(value: boolean): Promise<BotState>;
  minimize(): Promise<void>;
  close(): Promise<void>;
  openExternal(key: "tg" | "vk" | "yt"): Promise<void>;
  onState(handler: (state: BotState) => void): () => void;
  onError(handler: (message: string) => void): () => void;
};

interface Window {
  bloodweb: BloodwebApi;
}

type BotItem = {
  id: string;
  label: string;
  thumbnail?: string | null;
  position: number;
  subtitle?: string;
};

type QueueItem = BotItem & {
  action?: "item" | "center";
  score?: number;
  node_id?: string;
};

type BotSettings = Record<string, number | boolean | string | undefined>;

type TemplateRecord = { name: string; section: string; index: number };

type CenterState = {
  state: "CENTER_UNCONFIGURED" | "CENTER_CONFIRMED" | "CENTER_RECHECKING" | "CENTER_NOT_CONFIRMED";
  configured: boolean;
  name: string;
  node_id: string;
  score?: number | null;
  threshold: number;
  message: string;
  clicks_allowed: boolean;
  setup_active: boolean;
  pending: boolean;
  pending_thumbnail?: string | null;
};

type ReferenceCaptureState = {
  active: boolean;
  pending: boolean;
  pending_thumbnail?: string | null;
};

type BotState = {
  app_name?: string;
  app_version?: string;
  status: string;
  status_message: string;
  grid_visible: boolean;
  grid_message: string;
  adding_capture: boolean;
  center?: CenterState;
  reference_capture?: ReferenceCaptureState;
  always_on_top: boolean;
  current_template: string;
  templates: TemplateRecord[];
  priority_items: BotItem[];
  template_items: BotItem[];
  queue: QueueItem[];
  next_click: QueueItem | null;
  is_running: boolean;
  settings: BotSettings;
  logs: string[];
  last_error?: string | null;
  emergency_stop_reason?: string | null;
  safety_terms_version?: number;
  safety_consent_accepted?: boolean;
  safety_consent_required?: boolean;
};

type ListName = "priority" | "template";
type TemplateAction = "create" | "rename" | "duplicate" | "delete";

let state: BotState | null = null;
let settingsTab: "general" | "recognition" | "timing" | "mouse" | "log" = "general";
let logViewCleared = false;
let templateMenuOpen = false;
let selectedPriorityIndex: number | null = null;
let selectedTemplateIndex: number | null = null;
let activeTemplateAction: TemplateAction | null = null;
let activeItemEdit: { list: ListName; index: number } | null = null;
let activeRemoveItem: { list: ListName; index: number } | null = null;

const APP_DISPLAY_NAME_EN = "DBD Autoclicker Bloodweb";
const APP_DISPLAY_NAME_RU = "DBD Автокликер Bloodweb";

type UiLanguage = "ru" | "en";
type TextKey =
  | "ready" | "done" | "settings" | "learning" | "grid" | "hideGrid" | "screenshot" | "cancel"
  | "priority" | "template" | "currentTemplate" | "priorityEmpty" | "templateEmpty"
  | "test" | "start" | "stop" | "queue" | "testNotStarted" | "nextNone" | "next"
  | "hint" | "pinOn" | "pinOff" | "center" | "setupCenter" | "centerConfirmed" | "centerRechecking" | "centerMissing"
  | "centerTipSetup" | "centerTipConfirmed" | "centerTipRechecking" | "centerTipMissing"
  | "editGrid" | "confirmCenterFirst" | "addReference" | "general" | "recognition" | "timing" | "mouse" | "log"
  | "alwaysOnTop" | "savedInUiState" | "version" | "goLog" | "language" | "russian" | "english"
  | "copyLog" | "clearLog" | "emptyLog" | "save" | "numericError" | "detailRangeError"
  | "tutorialTitle" | "tutorialIntroTitle" | "tutorialIntro" | "tutorialCenterTitle" | "tutorialCenterText"
  | "tutorialGridTitle" | "tutorialGridText" | "tutorialShotTitle" | "tutorialShotText" | "tutorialRunTitle" | "tutorialRunText"
  | "videos" | "videoPending1" | "videoPending2" | "close" | "deleteItem" | "delete" | "editItem"
  | "name" | "emptyName" | "saveShot" | "saveCenter" | "ok" | "createTemplate" | "renameTemplate" | "duplicateTemplate"
  | "deleteTemplate" | "newTemplate" | "templateName" | "newName" | "duplicateName" | "templateExists";

const TEXT: Record<UiLanguage, Record<TextKey, string>> = {
  ru: {
    ready: "Готов", done: "Готово", settings: "Настройки", learning: "Обучение", grid: "▦ Паутина", hideGrid: "▦ Скрыть паутину",
    screenshot: "Скрин", cancel: "Отмена", priority: "Приоритет", template: "Шаблон", currentTemplate: "Текущий шаблон",
    priorityEmpty: "В приоритете пусто", templateEmpty: "В шаблоне пусто", test: "Тест", start: "Start", stop: "■ Stop · F8",
    queue: "Очередь кликов", testNotStarted: "Тест ещё не запускался", nextNone: "Следующий клик не выбран", next: "Следующий",
    hint: "Тест строит очередь без кликов. Start выполняет её. Ручное движение мыши останавливает работу.",
    pinOn: "Закрепить поверх всех окон", pinOff: "Открепить от других окон", center: "⊕ Центр", setupCenter: "⊕ Настроить центр",
    centerConfirmed: "● Центр распознан", centerRechecking: "● Перепроверка центра", centerMissing: "● Центр не распознан",
    centerTipSetup: "Нажмите, чтобы настроить или перезаписать центр.", centerTipConfirmed: "Центр Bloodweb подтверждён. Автоклик разрешён.",
    centerTipRechecking: "Клики временно заблокированы: идёт перепроверка центра.", centerTipMissing: "Центр Bloodweb не подтверждён. Автоклик заблокирован.",
    editGrid: "Редактировать паутину", confirmCenterFirst: "Сначала подтвердите центр Bloodweb", addReference: "Добавить скрин эталона",
    general: "Общие", recognition: "Распознавание", timing: "Тайминги", mouse: "Мышь", log: "Лог", alwaysOnTop: "Поверх всех окон",
    savedInUiState: "Сохраняется в db/ui_state.json", version: "Версия", goLog: "Перейти к логу", language: "Язык",
    russian: "Русский", english: "English", copyLog: "Скопировать лог", clearLog: "Очистить вид", emptyLog: "Лог пуст",
    save: "Сохранить", numericError: "Введите числовые значения", detailRangeError: "Минимум детальной проверки больше максимума",
    tutorialTitle: "Обучение", tutorialIntroTitle: "Быстрый порядок работы",
    tutorialIntro: "Откройте Bloodweb, настройте центр и паутину, добавьте эталоны, проверьте очередь через «Тест», затем запускайте Start.",
    tutorialCenterTitle: "Центр", tutorialCenterText: "Впишите круг и шестиугольник в центральный узел, при необходимости подмасштабируйте мышью.",
    tutorialGridTitle: "Паутина", tutorialGridText: "Совместите узлы с Bloodweb. Первый масштаб берется из настроенного центра, дальше сохраняется ваш размер.",
    tutorialShotTitle: "Скрины", tutorialShotText: "Нажмите «Скрин», выберите узел по сетке, задайте имя и сохраните эталон в текущий шаблон.",
    tutorialRunTitle: "Проверка", tutorialRunText: "«Тест» строит очередь без кликов. Start кликает только после подтвержденного центра.",
    videos: "Видео", videoPending1: "Видео 1 будет добавлено позже", videoPending2: "Видео 2 будет добавлено позже", close: "Закрыть",
    deleteItem: "Удалить элемент", delete: "Удалить", editItem: "Редактировать элемент", name: "Название:", emptyName: "Название не может быть пустым",
    saveShot: "Сохранить скрин", saveCenter: "Сохранить центр Bloodweb", ok: "ОК", createTemplate: "Новый шаблон",
    renameTemplate: "Переименовать", duplicateTemplate: "Дублировать", deleteTemplate: "Удалить шаблон", newTemplate: "Новый шаблон",
    templateName: "Название шаблона", newName: "Новое название", duplicateName: "Название копии", templateExists: "Шаблон с таким именем уже есть",
  },
  en: {
    ready: "Ready", done: "Ready", settings: "Settings", learning: "Guide", grid: "▦ Grid", hideGrid: "▦ Hide grid",
    screenshot: "Shot", cancel: "Cancel", priority: "Priority", template: "Template", currentTemplate: "Current template",
    priorityEmpty: "Priority is empty", templateEmpty: "Template is empty", test: "Test", start: "Start", stop: "■ Stop · F8",
    queue: "Click Queue", testNotStarted: "Test has not run yet", nextNone: "No next click selected", next: "Next",
    hint: "Test builds the queue without clicking. Start runs it. Manual mouse movement stops the bot.",
    pinOn: "Keep on top", pinOff: "Stop keeping on top", center: "⊕ Center", setupCenter: "⊕ Set center",
    centerConfirmed: "● Center detected", centerRechecking: "● Rechecking center", centerMissing: "● Center not detected",
    centerTipSetup: "Click to set or replace the center.", centerTipConfirmed: "Bloodweb center is confirmed. Autoclick is allowed.",
    centerTipRechecking: "Clicks are temporarily blocked while the center is being rechecked.", centerTipMissing: "Bloodweb center is not confirmed. Autoclick is blocked.",
    editGrid: "Edit grid", confirmCenterFirst: "Confirm the Bloodweb center first", addReference: "Add reference screenshot",
    general: "General", recognition: "Recognition", timing: "Timing", mouse: "Mouse", log: "Log", alwaysOnTop: "Always on top",
    savedInUiState: "Saved in db/ui_state.json", version: "Version", goLog: "Go to log", language: "Language",
    russian: "Русский", english: "English", copyLog: "Copy log", clearLog: "Clear view", emptyLog: "Log is empty",
    save: "Save", numericError: "Enter numeric values", detailRangeError: "Detailed check minimum is greater than maximum",
    tutorialTitle: "Guide", tutorialIntroTitle: "Quick workflow",
    tutorialIntro: "Open Bloodweb, set the center and grid, add references, check the queue with Test, then press Start.",
    tutorialCenterTitle: "Center", tutorialCenterText: "Fit the circle and hexagon into the center node. Resize with the mouse if needed.",
    tutorialGridTitle: "Grid", tutorialGridText: "Align the nodes with Bloodweb. The first scale is based on the center; your later size is saved.",
    tutorialShotTitle: "Screenshots", tutorialShotText: "Press Shot, select a grid node, enter a name, and save the reference to the current template.",
    tutorialRunTitle: "Check", tutorialRunText: "Test builds the queue without clicks. Start clicks only after the center is confirmed.",
    videos: "Videos", videoPending1: "Video 1 will be added later", videoPending2: "Video 2 will be added later", close: "Close",
    deleteItem: "Delete item", delete: "Delete", editItem: "Edit item", name: "Name:", emptyName: "Name cannot be empty",
    saveShot: "Save screenshot", saveCenter: "Save Bloodweb center", ok: "OK", createTemplate: "New template",
    renameTemplate: "Rename", duplicateTemplate: "Duplicate", deleteTemplate: "Delete template", newTemplate: "New template",
    templateName: "Template name", newName: "New name", duplicateName: "Copy name", templateExists: "A template with this name already exists",
  },
};

function lang(): UiLanguage {
  return state?.settings?.ui_language === "en" ? "en" : "ru";
}

function t(key: TextKey): string {
  return TEXT[lang()][key];
}

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element as T;
};

function ensureSafetyDom(): void {
  if (!document.getElementById("centerButton")) {
    const button = document.createElement("button");
    button.id = "centerButton";
    button.className = "btn center unconfigured";
    button.title = "Нажмите, чтобы настроить или перезаписать центр";
    button.textContent = "⊕ Центр";
    const grid = document.getElementById("gridButton");
    grid?.parentElement?.insertBefore(button, grid);
  }
  if (!document.getElementById("centerSaveModal")) {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="centerSaveModal" class="modal-backdrop" aria-hidden="true">
        <section class="modal compact-modal">
          <header class="modal-head">
            <strong>Сохранить центр Bloodweb</strong>
            <button class="modal-close" data-close="centerSaveModal">×</button>
          </header>
          <form id="centerSaveForm" class="modal-body"></form>
          <footer id="centerSaveFooter" class="modal-actions"></footer>
        </section>
      </div>
    `);
  }
  if (!document.getElementById("referenceSaveModal")) {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="referenceSaveModal" class="modal-backdrop" aria-hidden="true">
        <section class="modal compact-modal">
          <header class="modal-head">
            <strong>Сохранить скрин</strong>
            <button class="modal-close" data-close="referenceSaveModal">×</button>
          </header>
          <form id="referenceSaveForm" class="modal-body"></form>
          <footer id="referenceSaveFooter" class="modal-actions"></footer>
        </section>
      </div>
    `);
  }
  if (!document.getElementById("removeConfirmModal")) {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="removeConfirmModal" class="modal-backdrop" aria-hidden="true">
        <section class="modal compact-modal">
          <header class="modal-head">
            <strong>Удалить элемент</strong>
            <button class="modal-close" data-close="removeConfirmModal">×</button>
          </header>
          <div id="removeConfirmBody" class="modal-body"></div>
          <footer id="removeConfirmFooter" class="modal-actions"></footer>
        </section>
      </div>
    `);
  }
  if (!document.getElementById("tutorialModal")) {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="tutorialModal" class="modal-backdrop" aria-hidden="true">
        <section class="modal tutorial-modal">
          <header class="modal-head">
            <strong id="tutorialTitle">${t("tutorialTitle")}</strong>
            <button class="modal-close" data-close="tutorialModal">×</button>
          </header>
          <div class="modal-body tutorial-body">
            <div class="tutorial-intro">
              <strong id="tutorialIntroTitle">${t("tutorialIntroTitle")}</strong>
              <span id="tutorialIntroText">${t("tutorialIntro")}</span>
            </div>
            <div class="tutorial-steps">
              <div class="tutorial-step-card">
                <img src="../../gif/01%20Chentr%20(1)%20(1).gif" alt="Настройка центра">
                <div><b>1</b><span id="tutorialStep1Title">${t("tutorialCenterTitle")}</span><small id="tutorialStep1Text">${t("tutorialCenterText")}</small></div>
              </div>
              <div class="tutorial-step-card">
                <img src="../../gif/02%20Setka%20(1)%20(1).gif" alt="Настройка паутины">
                <div><b>2</b><span id="tutorialStep2Title">${t("tutorialGridTitle")}</span><small id="tutorialStep2Text">${t("tutorialGridText")}</small></div>
              </div>
              <div class="tutorial-step-card">
                <img src="../../gif/03%20Skrin%20(1)%20(1).gif" alt="Создание скрина узла">
                <div><b>3</b><span id="tutorialStep3Title">${t("tutorialShotTitle")}</span><small id="tutorialStep3Text">${t("tutorialShotText")}</small></div>
              </div>
              <div class="tutorial-step-card">
                <img src="../../gif/04%20Start%20(1)%20(1).gif" alt="Проверка и запуск">
                <div><b>4</b><span id="tutorialStep4Title">${t("tutorialRunTitle")}</span><small id="tutorialStep4Text">${t("tutorialRunText")}</small></div>
              </div>
            </div>
            <div class="tutorial-video-list">
              <strong id="tutorialVideosTitle">${t("videos")}</strong>
              <button id="tutorialVideo1" class="smallbtn" type="button" disabled>${t("videoPending1")}</button>
              <button id="tutorialVideo2" class="smallbtn" type="button" disabled>${t("videoPending2")}</button>
            </div>
            <div class="tutorial-links">
              <button id="tutorialVkLink" class="smallbtn" type="button">VK AurumWise</button>
              <button id="tutorialTgLink" class="smallbtn" type="button">TG AurumWise</button>
            </div>
          </div>
          <footer class="modal-actions">
            <button id="tutorialClose" class="smallbtn" data-close="tutorialModal" type="button">${t("close")}</button>
          </footer>
        </section>
      </div>
    `);
  }
  if (!document.getElementById("safetyConsentModal")) {
    document.body.insertAdjacentHTML("beforeend", `
      <div id="safetyConsentModal" class="modal-backdrop required" aria-hidden="true">
        <section class="modal compact-modal safety-modal">
          <header class="modal-head"><strong>ВНИМАНИЕ</strong></header>
          <div class="modal-body safety-copy">
            <p>Программа временно управляет курсором мыши: перемещает его и выполняет клики по результатам локального распознавания изображений.</p>
            <p>Распознавание, положение сетки, интерфейс игры и внешние условия могут меняться. Программа может ошибиться и выполнить клик не по тому элементу.</p>
            <p>Используйте программу только при открытом Bloodweb и только под личным контролем.</p>
            <p>Перед запуском убедитесь, что центр Bloodweb настроен и распознан, сетка правильно совмещена, и вы готовы немедленно остановить программу клавишей F8 или кнопкой Stop.</p>
            <label class="consent-check">
              <input id="safetyConsentCheck" type="checkbox">
              <span>Я понимаю риски, принимаю ответственность за использование программы и отказываюсь от претензий к автору в пределах, допустимых применимым правом.</span>
            </label>
          </div>
          <footer class="modal-actions">
            <button id="safetyConsentClose" class="smallbtn" type="button">Закрыть</button>
            <button id="safetyConsentContinue" class="smallbtn" type="button" disabled>Продолжить</button>
          </footer>
        </section>
      </div>
    `);
  }
}

async function command(name: string, payload: Record<string, unknown> = {}): Promise<boolean> {
  try {
    const result = await window.bloodweb.command<BotState>(name, payload);
    render(result);
    return true;
  } catch (error) {
    showTransientError(String(error));
    return false;
  }
}

async function commandForModal(name: string, payload: Record<string, unknown>): Promise<boolean> {
  try {
    const result = await window.bloodweb.command<BotState>(name, payload);
    closeModal("templateActionModal");
    activeTemplateAction = null;
    render(result);
    return true;
  } catch (error) {
    const errorBox = document.getElementById("templateActionError");
    if (errorBox) {
      errorBox.textContent = String(error).replace(/^Error:\s*/, "");
    }
    return false;
  }
}

function handleAddCaptureClick(): void {
  if (!state) return;
  if (state.adding_capture || state.reference_capture?.pending) {
    void command("cancelReferenceCapture");
    return;
  }
  if (!state.adding_capture) {
    void command("openAddCapture");
    return;
  }
}

function render(nextState: BotState): void {
  ensureSafetyDom();
  state = nextState;
  clampSelections();
  renderStaticText();
  renderTitlebar();
  renderToolbar();
  renderCenterButton();
  renderGridAvailability();
  renderLists();
  renderRunPanel();
  renderQueue();
  renderTemplateDropdown();
  renderCenterSaveModal();
  renderReferenceSaveModal();
  renderSafetyConsentModal();
  if (isOpen("settingsModal")) renderSettingsModal();
  if (isOpen("templateActionModal") && activeTemplateAction === "delete") renderTemplateActionModal("delete");
  if (isOpen("itemEditModal") && activeItemEdit) renderItemEditModal(activeItemEdit.list, activeItemEdit.index);
  if (isOpen("removeConfirmModal") && activeRemoveItem) renderRemoveConfirmModal();
}

function setText(id: string, value: string): void {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function setTitle(id: string, value: string): void {
  const element = document.getElementById(id);
  if (element) element.title = value;
}

function renderStaticText(): void {
  const appDisplayName = lang() === "ru" ? APP_DISPLAY_NAME_RU : APP_DISPLAY_NAME_EN;
  const version = state?.app_version ? `v${state.app_version}` : "";
  document.title = version ? `${appDisplayName} ${version}` : appDisplayName;
  const title = document.querySelector(".title");
  if (title) title.textContent = appDisplayName;
  const footerName = document.querySelector(".social-footer span:first-child");
  if (footerName) footerName.textContent = appDisplayName;
  setTitle("settingsButton", t("settings"));
  setTitle("tutorialButton", t("learning"));
  setText("testButton", t("test"));
  setText("startButton", t("start"));
  setText("stopButton", t("stop"));
  const priorityHead = document.querySelector(".lists-grid .section:first-child .section-head strong");
  if (priorityHead) priorityHead.textContent = t("priority");
  setTitle("priorityUp", lang() === "en" ? "Move up" : "Поднять");
  setTitle("priorityDown", lang() === "en" ? "Move down" : "Опустить");
  setTitle("priorityToTemplate", lang() === "en" ? "Move to current template" : "Перенести в текущий шаблон");
  setTitle("priorityEdit", t("editItem"));
  setTitle("priorityRemove", t("delete"));
  setTitle("templatePicker", lang() === "en" ? "Select template" : "Выбрать шаблон");
  setTitle("templateCreate", t("createTemplate"));
  setTitle("templateRename", t("renameTemplate"));
  setTitle("templateDuplicate", t("duplicateTemplate"));
  setTitle("templateDelete", t("deleteTemplate"));
  setTitle("templateUp", lang() === "en" ? "Move up" : "Поднять");
  setTitle("templateDown", lang() === "en" ? "Move down" : "Опустить");
  setTitle("templateToPriority", lang() === "en" ? "Move to priority" : "Перенести в приоритет");
  setTitle("templateEdit", t("editItem"));
  setTitle("templateRemove", t("delete"));
  const queueHead = document.querySelector(".queue-panel .section-head strong");
  if (queueHead) queueHead.textContent = t("queue");
  const hint = document.querySelector(".hint");
  if (hint) hint.textContent = t("hint");
  const settingsTitle = document.querySelector("#settingsModal .modal-head strong");
  if (settingsTitle) settingsTitle.textContent = t("settings");
  const centerSaveTitle = document.querySelector("#centerSaveModal .modal-head strong");
  if (centerSaveTitle) centerSaveTitle.textContent = t("saveCenter");
  const referenceSaveTitle = document.querySelector("#referenceSaveModal .modal-head strong");
  if (referenceSaveTitle) referenceSaveTitle.textContent = t("saveShot");
  const removeConfirmTitle = document.querySelector("#removeConfirmModal .modal-head strong");
  if (removeConfirmTitle) removeConfirmTitle.textContent = t("deleteItem");
  setText("tutorialTitle", t("tutorialTitle"));
  setText("tutorialIntroTitle", t("tutorialIntroTitle"));
  setText("tutorialIntroText", t("tutorialIntro"));
  setText("tutorialStep1Title", t("tutorialCenterTitle"));
  setText("tutorialStep1Text", t("tutorialCenterText"));
  setText("tutorialStep2Title", t("tutorialGridTitle"));
  setText("tutorialStep2Text", t("tutorialGridText"));
  setText("tutorialStep3Title", t("tutorialShotTitle"));
  setText("tutorialStep3Text", t("tutorialShotText"));
  setText("tutorialStep4Title", t("tutorialRunTitle"));
  setText("tutorialStep4Text", t("tutorialRunText"));
  setText("tutorialVideosTitle", t("videos"));
  setText("tutorialVideo1", t("videoPending1"));
  setText("tutorialVideo2", t("videoPending2"));
  setText("tutorialClose", t("close"));
  const safetyTitle = document.querySelector("#safetyConsentModal .modal-head strong");
  if (safetyTitle) safetyTitle.textContent = lang() === "en" ? "WARNING" : "ВНИМАНИЕ";
  const safetyParagraphs = document.querySelectorAll("#safetyConsentModal .safety-copy p");
  const safetyTexts = lang() === "en"
    ? [
      "The program temporarily controls the mouse cursor: it moves it and performs clicks based on local image recognition.",
      "Recognition, grid position, game UI, and external conditions can change. The program may make a mistake and click the wrong element.",
      "Use the program only while Bloodweb is open and only under your personal control.",
      "Before starting, make sure the Bloodweb center is set and recognized, the grid is aligned, and you are ready to stop the program with F8 or Stop.",
    ]
    : [
      "Программа временно управляет курсором мыши: перемещает его и выполняет клики по результатам локального распознавания изображений.",
      "Распознавание, положение сетки, интерфейс игры и внешние условия могут меняться. Программа может ошибиться и выполнить клик не по тому элементу.",
      "Используйте программу только при открытом Bloodweb и только под личным контролем.",
      "Перед запуском убедитесь, что центр Bloodweb настроен и распознан, сетка правильно совмещена, и вы готовы немедленно остановить программу клавишей F8 или кнопкой Stop.",
    ];
  safetyParagraphs.forEach((paragraph, index) => {
    paragraph.textContent = safetyTexts[index] || paragraph.textContent;
  });
  const consentText = document.querySelector("#safetyConsentModal .consent-check span");
  if (consentText) {
    consentText.textContent = lang() === "en"
      ? "I understand the risks, accept responsibility for using the program, and waive claims against the author to the extent allowed by applicable law."
      : "Я понимаю риски, принимаю ответственность за использование программы и отказываюсь от претензий к автору в пределах, допустимых применимым правом.";
  }
  setText("safetyConsentClose", t("close"));
  setText("safetyConsentContinue", lang() === "en" ? "Continue" : "Продолжить");
  const tabs: Array<[string, TextKey]> = [["general", "general"], ["recognition", "recognition"], ["timing", "timing"], ["mouse", "mouse"], ["log", "log"]];
  tabs.forEach(([tab, key]) => {
    const button = document.querySelector(`[data-settings-tab="${tab}"]`);
    if (button) button.textContent = t(key);
  });
}

function clampSelections(): void {
  if (!state) return;
  if (selectedPriorityIndex !== null && selectedPriorityIndex >= state.priority_items.length) selectedPriorityIndex = null;
  if (selectedTemplateIndex !== null && selectedTemplateIndex >= state.template_items.length) selectedTemplateIndex = null;
}

function renderTitlebar(): void {
  if (!state) return;
  const statusPill = $("statusPill");
  statusPill.className = "status-pill";
  if (state.status === "Тест") statusPill.classList.add("test");
  if (state.status === "Работа") statusPill.classList.add("running");
  if (state.status === "Пауза") statusPill.classList.add("paused");
  if (state.status === "Стоп") statusPill.classList.add("paused");
  if (state.status === "Ошибка") statusPill.classList.add("error");
  statusPill.querySelector("b")!.textContent = translateStatus(state.status) || t("ready");

  const pin = $("pinButton");
  pin.classList.toggle("pinned", Boolean(state.always_on_top));
  pin.title = state.always_on_top ? t("pinOff") : t("pinOn");
}

function translateStatus(value: string): string {
  if (lang() === "ru") return value;
  return ({
    "Готов": "Ready",
    "Тест": "Test",
    "Работа": "Running",
    "Пауза": "Paused",
    "Стоп": "Stopped",
    "Ошибка": "Error",
  } as Record<string, string>)[value] || value;
}

function renderToolbar(): void {
  if (!state) return;
  const grid = $("gridButton") as HTMLButtonElement;
  const addCapture = $("addCaptureButton") as HTMLButtonElement;
  const captureActive = state.adding_capture || Boolean(state.reference_capture?.pending);
  grid.textContent = state.grid_visible ? t("hideGrid") : t("grid");
  grid.classList.toggle("active", state.grid_visible);
  addCapture.textContent = captureActive ? t("cancel") : t("screenshot");
  addCapture.classList.toggle("active", captureActive);
  $("gridMessage").textContent = state.grid_message;
}

function renderCenterButton(): void {
  const center = state?.center;
  const button = $("centerButton") as HTMLButtonElement;
  button.className = "btn center";
  const centerState = center?.state || "CENTER_UNCONFIGURED";
  button.classList.add(centerState.toLowerCase().replace("center_", ""));
  const labels: Record<string, string> = {
    CENTER_UNCONFIGURED: t("setupCenter"),
    CENTER_CONFIRMED: t("centerConfirmed"),
    CENTER_RECHECKING: t("centerRechecking"),
    CENTER_NOT_CONFIRMED: t("centerMissing"),
  };
  const tips: Record<string, string> = {
    CENTER_UNCONFIGURED: t("centerTipSetup"),
    CENTER_CONFIRMED: t("centerTipConfirmed"),
    CENTER_RECHECKING: t("centerTipRechecking"),
    CENTER_NOT_CONFIRMED: t("centerTipMissing"),
  };
  button.textContent = labels[centerState] || t("center");
  button.title = lang() === "en" ? tips[centerState] || "" : center?.message || tips[centerState] || "";
}

function renderGridAvailability(): void {
  if (!state) return;
  const grid = $("gridButton") as HTMLButtonElement;
  const addCapture = $("addCaptureButton") as HTMLButtonElement;
  const available = state.center?.state === "CENTER_CONFIRMED";
  grid.disabled = !available;
  grid.title = available ? t("editGrid") : t("confirmCenterFirst");
  addCapture.disabled = !available;
  addCapture.title = available ? t("addReference") : t("confirmCenterFirst");
}

function renderLists(): void {
  if (!state) return;
  $("priorityCount").textContent = `${state.priority_items.length}`;
  $("templateCount").textContent = `${state.template_items.length}`;
  $("templateTitle").textContent = state.current_template || t("currentTemplate");
  renderItemList($("priorityList"), state.priority_items, t("priorityEmpty"), "priority", selectedPriorityIndex);
  renderItemList($("templateList"), state.template_items, t("templateEmpty"), "template", selectedTemplateIndex);
  renderListActions();
}

function renderItemList(container: HTMLElement, items: BotItem[], empty: string, list: ListName, selectedIndex: number | null): void {
  if (!items.length) {
    container.innerHTML = `<div class="empty">${empty}</div>`;
    return;
  }
  container.innerHTML = items.map((item, index) => `
    <button class="item ${selectedIndex === index ? "selected" : ""}" data-list="${list}" data-index="${index}" title="${escapeHtml(item.label)}">
      ${thumb(item)}
      <span>
        <span class="item-name">${escapeHtml(item.label)}</span>
        <span class="item-sub">${escapeHtml(item.subtitle || "")}</span>
      </span>
      <span class="item-badge">${item.position}</span>
    </button>
  `).join("");
  container.querySelectorAll<HTMLButtonElement>(".item").forEach((item) => {
    item.addEventListener("click", () => {
      const index = Number(item.dataset.index);
      if (list === "priority") selectedPriorityIndex = index;
      if (list === "template") selectedTemplateIndex = index;
      renderLists();
    });
  });
}

function renderListActions(): void {
  if (!state) return;
  const prioritySelected = selectedPriorityIndex !== null;
  const templateSelected = selectedTemplateIndex !== null;
  setDisabled("priorityUp", !prioritySelected || selectedPriorityIndex === 0);
  setDisabled("priorityDown", !prioritySelected || selectedPriorityIndex === state.priority_items.length - 1);
  setDisabled("priorityToTemplate", !prioritySelected);
  setDisabled("priorityEdit", !prioritySelected);
  setDisabled("priorityRemove", !prioritySelected);
  setDisabled("templateUp", !templateSelected || selectedTemplateIndex === 0);
  setDisabled("templateDown", !templateSelected || selectedTemplateIndex === state.template_items.length - 1);
  setDisabled("templateToPriority", !templateSelected);
  setDisabled("templateEdit", !templateSelected);
  setDisabled("templateRemove", !templateSelected);
}

function setDisabled(id: string, disabled: boolean): void {
  ($<HTMLButtonElement>(id)).disabled = disabled;
}

function renderTemplateDropdown(): void {
  if (!state) return;
  const picker = $("templatePicker");
  const menu = $("templateMenu");
  picker.classList.toggle("open", templateMenuOpen);
  menu.classList.toggle("open", templateMenuOpen);
  menu.setAttribute("aria-hidden", templateMenuOpen ? "false" : "true");
  menu.innerHTML = state.templates.map((template) => `
    <button class="template-option ${template.name === state!.current_template ? "active" : ""}" data-template="${escapeHtml(template.name)}" title="${escapeHtml(template.name)}">
      ${escapeHtml(template.name)}
    </button>
  `).join("");
  menu.querySelectorAll<HTMLButtonElement>(".template-option").forEach((button) => {
    button.addEventListener("click", () => {
      templateMenuOpen = false;
      selectedTemplateIndex = null;
      void command("setTemplate", { name: button.dataset.template || "" });
    });
  });
}

function renderRunPanel(): void {
  if (!state) return;
  $("runStatus").textContent = translateStatus(state.status) || t("ready");
  $("runMessage").textContent = lang() === "en" ? t("done") : state.status_message || t("done");
  $("nextClick").textContent = state.next_click ? `${t("next")}: ${state.next_click.label}` : t("nextNone");
  const startBlocked =
    state.is_running ||
    !state.safety_consent_accepted ||
    !state.center?.configured ||
    state.center?.state !== "CENTER_CONFIRMED" ||
    Boolean(state.emergency_stop_reason && state.center?.state !== "CENTER_CONFIRMED");
  ($("startButton") as HTMLButtonElement).disabled = startBlocked;
  $("stopButton").textContent = t("stop");
  ($("stopButton") as HTMLButtonElement).disabled = !state.is_running && state.status !== "Работа";
}

function renderQueue(): void {
  if (!state) return;
  $("queueCount").textContent = state.queue.length ? `${state.queue.length}` : t("testNotStarted");
  const list = $("queueList");
  if (!state.queue.length) {
    list.innerHTML = `<div class="queue-empty">${t("testNotStarted")}</div>`;
    return;
  }
  const nextId = state.next_click?.id;
  list.innerHTML = state.queue.map((item, index) => {
    const center = item.action === "center" || item.id === "center";
    const current = nextId ? item.id === nextId : index === 0;
    return `
      <div class="queue-card ${center ? "center" : ""} ${current ? "current" : ""}">
        <em>${item.position || index + 1}</em>
        ${center ? `<div class="thumb">◎</div>` : thumb(item)}
        <span>${escapeHtml(item.label)}</span>
      </div>
    `;
  }).join("");
}

function thumb(item: Pick<BotItem, "thumbnail" | "label">): string {
  if (!item.thumbnail) return `<div class="thumb">?</div>`;
  return `<div class="thumb"><img alt="${escapeHtml(item.label)}" src="${item.thumbnail}"></div>`;
}

function largeThumb(item: Pick<BotItem, "thumbnail" | "label">): string {
  if (!item.thumbnail) return `<div class="item-edit-image">?</div>`;
  return `<div class="item-edit-image"><img alt="${escapeHtml(item.label)}" src="${item.thumbnail}"></div>`;
}

function openModal(id: string): void {
  $(id).classList.add("open");
  $(id).setAttribute("aria-hidden", "false");
}

function closeModal(id: string): void {
  $(id).classList.remove("open");
  $(id).setAttribute("aria-hidden", "true");
}

function isOpen(id: string): boolean {
  return $(id).classList.contains("open");
}

function itemForEdit(list: ListName, index: number): BotItem | null {
  if (!state) return null;
  const items = list === "priority" ? state.priority_items : state.template_items;
  return items[index] || null;
}

function openItemEdit(list: ListName, index: number): void {
  activeItemEdit = { list, index };
  openModal("itemEditModal");
  renderItemEditModal(list, index);
}

function openRemoveConfirm(list: ListName, index: number): void {
  activeRemoveItem = { list, index };
  openModal("removeConfirmModal");
  renderRemoveConfirmModal();
}

function renderRemoveConfirmModal(): void {
  if (!activeRemoveItem) {
    closeModal("removeConfirmModal");
    return;
  }
  const item = itemForEdit(activeRemoveItem.list, activeRemoveItem.index);
  if (!item) {
    closeModal("removeConfirmModal");
    activeRemoveItem = null;
    return;
  }
  $("removeConfirmBody").innerHTML = `
    <div class="item-edit-preview">
      ${largeThumb(item)}
      <div class="delete-copy">
        <strong>${escapeHtml(item.label)}</strong>
      </div>
    </div>
  `;
  $("removeConfirmFooter").innerHTML = `
    <button id="removeConfirmCancel" class="smallbtn" type="button">${t("cancel")}</button>
    <button id="removeConfirmOk" class="smallbtn danger" type="button">${t("delete")}</button>
  `;
  $("removeConfirmCancel").addEventListener("click", () => {
    closeModal("removeConfirmModal");
    activeRemoveItem = null;
  });
  $("removeConfirmOk").addEventListener("click", confirmRemoveItem);
}

async function confirmRemoveItem(): Promise<void> {
  if (!activeRemoveItem) return;
  const target = activeRemoveItem;
  activeRemoveItem = null;
  selectedPriorityIndex = target.list === "priority" ? null : selectedPriorityIndex;
  selectedTemplateIndex = target.list === "template" ? null : selectedTemplateIndex;
  closeModal("removeConfirmModal");
  await command("removeItem", { list: target.list, index: target.index });
}

function renderItemEditModal(list: ListName, index: number): void {
  const item = itemForEdit(list, index);
  if (!item) {
    closeModal("itemEditModal");
    activeItemEdit = null;
    return;
  }
  $("itemEditTitle").textContent = t("editItem");
  const form = $("itemEditForm") as HTMLFormElement;
  const footer = $("itemEditFooter");
  form.innerHTML = `
    <div class="item-edit-preview">
      ${largeThumb(item)}
      <label class="modal-field">
        <span>${t("name")}</span>
        <input id="itemEditInput" class="setting-input" value="${escapeHtml(item.label)}">
      </label>
    </div>
    <div id="itemEditError" class="error-line"></div>
  `;
  footer.innerHTML = `
    <button id="itemEditCancel" class="smallbtn" type="button">${t("cancel")}</button>
    <button id="itemEditOk" class="smallbtn" type="submit">${t("ok")}</button>
  `;
  $("itemEditCancel").addEventListener("click", () => {
    closeModal("itemEditModal");
    activeItemEdit = null;
  });
  form.onsubmit = (event) => {
    event.preventDefault();
    submitItemEdit();
  };
  $("itemEditOk").addEventListener("click", (event) => {
    event.preventDefault();
    submitItemEdit();
  });
  const input = $("itemEditInput") as HTMLInputElement;
  setTimeout(() => {
    input.focus();
    input.select();
  }, 0);
}

async function submitItemEdit(): Promise<void> {
  if (!activeItemEdit) return;
  const input = $("itemEditInput") as HTMLInputElement;
  const label = input.value.trim();
  if (!label) {
    $("itemEditError").textContent = t("emptyName");
    return;
  }
  try {
    const result = await window.bloodweb.command<BotState>("renameItem", {
      list: activeItemEdit.list,
      index: activeItemEdit.index,
      label,
    });
    closeModal("itemEditModal");
    activeItemEdit = null;
    render(result);
  } catch (error) {
    $("itemEditError").textContent = String(error).replace(/^Error:\s*/, "");
  }
}

function openTemplateAction(action: TemplateAction): void {
  activeTemplateAction = action;
  openModal("templateActionModal");
  renderTemplateActionModal(action);
}

function renderTemplateActionModal(action: TemplateAction): void {
  if (!state) return;
  const title = $("templateActionTitle");
  const form = $("templateActionForm") as HTMLFormElement;
  const footer = $("templateActionFooter");
  const current = state.current_template || "";
  const templates = state.templates.map((template) => template.name);
  const defaultCopyName = uniqueName(`${current} copy`, templates);
  const config = {
    create: { title: t("createTemplate"), label: t("name"), value: "", ok: lang() === "en" ? "Create" : "Создать" },
    rename: { title: t("renameTemplate"), label: `${t("newName")}:`, value: current, ok: t("save") },
    duplicate: { title: t("duplicateTemplate"), label: `${t("duplicateName")}:`, value: defaultCopyName, ok: t("duplicateTemplate") },
    delete: { title: t("deleteTemplate"), label: `${t("template")}:`, value: current, ok: t("delete") },
  }[action];
  title.textContent = config.title;
  if (action === "delete") {
    form.innerHTML = `
      <label class="modal-field">
        <span>${config.label}</span>
        <select id="templateActionInput" class="setting-input">
          ${templates.map((name) => `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
        </select>
      </label>
      <div class="empty">${lang() === "en" ? "Deleting a template does not delete images used in other lists." : "Удаление шаблона не удаляет изображения, которые используются в других списках."}</div>
      <div id="templateDeleteConfirm" class="error-line">${t("deleteTemplate")} «${escapeHtml(current)}»?</div>
      <div id="templateActionError" class="error-line"></div>
    `;
    $("templateActionInput").addEventListener("change", (event) => {
      const name = (event.target as HTMLSelectElement).value;
      $("templateDeleteConfirm").textContent = `${t("deleteTemplate")} «${name}»?`;
    });
  } else {
    form.innerHTML = `
      <label class="modal-field">
        <span>${config.label}</span>
        <input id="templateActionInput" class="setting-input" value="${escapeHtml(config.value)}">
      </label>
      <div id="templateActionError" class="error-line"></div>
    `;
  }
  footer.innerHTML = `
    <button id="templateActionCancel" class="smallbtn" type="button">${t("cancel")}</button>
    <button id="templateActionOk" class="smallbtn ${action === "delete" ? "danger" : ""}" type="submit">${config.ok}</button>
  `;
  $("templateActionCancel").addEventListener("click", () => closeModal("templateActionModal"));
  form.onsubmit = (event) => {
    event.preventDefault();
    submitTemplateAction(action);
  };
  $("templateActionOk").addEventListener("click", (event) => {
    event.preventDefault();
    submitTemplateAction(action);
  });
  const input = $("templateActionInput") as HTMLInputElement | HTMLSelectElement;
  setTimeout(() => {
    input.focus();
    if (input instanceof HTMLInputElement) input.select();
  }, 0);
}

function submitTemplateAction(action: TemplateAction): void {
  if (!state) return;
  const input = $("templateActionInput") as HTMLInputElement | HTMLSelectElement;
  const name = input.value.trim();
  const error = $("templateActionError");
  if (!name) {
    error.textContent = t("emptyName");
    return;
  }
  const conflict = state.templates.some((template) => template.name === name);
  if ((action === "create" || action === "duplicate") && conflict) {
    error.textContent = t("templateExists");
    return;
  }
  if (action === "rename" && name !== state.current_template && conflict) {
    error.textContent = t("templateExists");
    return;
  }
  if (action === "create") void commandForModal("createTemplate", { name });
  if (action === "rename") void commandForModal("renameTemplate", { name });
  if (action === "duplicate") void commandForModal("duplicateTemplate", { name });
  if (action === "delete") void commandForModal("deleteTemplate", { name });
}

function uniqueName(base: string, existing: string[]): string {
  if (!existing.includes(base)) return base;
  let index = 2;
  while (existing.includes(`${base} ${index}`)) index += 1;
  return `${base} ${index}`;
}

function renderReferenceSaveModal(): void {
  if (!state) return;
  if (!state.reference_capture?.pending) {
    if (isOpen("referenceSaveModal")) closeModal("referenceSaveModal");
    return;
  }
  openModal("referenceSaveModal");
  const form = $("referenceSaveForm") as HTMLFormElement;
  const footer = $("referenceSaveFooter");
  form.innerHTML = `
    <div class="item-edit-preview">
      ${state.reference_capture.pending_thumbnail ? `<div class="item-edit-image"><img alt="Скрин узла" src="${state.reference_capture.pending_thumbnail}"></div>` : `<div class="item-edit-image">?</div>`}
      <label class="modal-field">
        <span>${t("name")}</span>
        <input id="referenceSaveName" class="setting-input" value="">
      </label>
    </div>
    <div id="referenceSaveError" class="error-line"></div>
  `;
  footer.innerHTML = `
    <button id="referenceSaveCancel" class="smallbtn" type="button">${t("cancel")}</button>
    <button id="referenceSaveOk" class="smallbtn" type="submit">${t("ok")}</button>
  `;
  $("referenceSaveCancel").addEventListener("click", () => command("cancelReferenceCapture"));
  form.onsubmit = (event) => {
    event.preventDefault();
    submitReferenceSave();
  };
  $("referenceSaveOk").addEventListener("click", (event) => {
    event.preventDefault();
    submitReferenceSave();
  });
  const input = $("referenceSaveName") as HTMLInputElement;
  setTimeout(() => input.focus(), 0);
}

function submitReferenceSave(): void {
  const input = $("referenceSaveName") as HTMLInputElement;
  const label = input.value.trim();
  if (!label) {
    $("referenceSaveError").textContent = t("emptyName");
    return;
  }
  void command("captureReference", { label });
}

function renderCenterSaveModal(): void {
  if (!state) return;
  if (!state.center?.pending) {
    if (isOpen("centerSaveModal")) closeModal("centerSaveModal");
    return;
  }
  openModal("centerSaveModal");
  const form = $("centerSaveForm") as HTMLFormElement;
  const footer = $("centerSaveFooter");
  form.innerHTML = `
    <div class="item-edit-preview">
      ${state.center.pending_thumbnail ? `<div class="item-edit-image"><img alt="Центр Bloodweb" src="${state.center.pending_thumbnail}"></div>` : `<div class="item-edit-image">?</div>`}
      <label class="modal-field">
        <span>${t("name")}</span>
        <input id="centerSaveName" class="setting-input" value="Центр Bloodweb">
      </label>
    </div>
    <div id="centerSaveError" class="error-line"></div>
  `;
  footer.innerHTML = `
    <button id="centerSaveCancel" class="smallbtn" type="button">${t("cancel")}</button>
    <button id="centerSaveOk" class="smallbtn" type="submit">${t("save")}</button>
  `;
  $("centerSaveCancel").addEventListener("click", () => command("cancelCenterAnchor"));
  form.onsubmit = (event) => {
    event.preventDefault();
    submitCenterSave();
  };
  $("centerSaveOk").addEventListener("click", (event) => {
    event.preventDefault();
    submitCenterSave();
  });
  const input = $("centerSaveName") as HTMLInputElement;
  setTimeout(() => {
    input.focus();
    input.select();
  }, 0);
}

function submitCenterSave(): void {
  const input = $("centerSaveName") as HTMLInputElement;
  const name = input.value.trim();
  if (!name) {
    $("centerSaveError").textContent = t("emptyName");
    return;
  }
  void command("saveCenterAnchor", { name });
}

function renderSafetyConsentModal(): void {
  if (!state) return;
  if (state.safety_consent_required) {
    openModal("safetyConsentModal");
  } else if (isOpen("safetyConsentModal")) {
    closeModal("safetyConsentModal");
  }
}

function settingsFieldsForTab(tab: typeof settingsTab): string[][] {
  const english = lang() === "en";
  const seconds = english ? "seconds" : "секунды";
  if (tab === "recognition") {
    return [
      ["threshold", english ? "Item confidence" : "Доверие к предметам", english ? "0.0-1.0, lower finds more, higher is stricter" : "0.0-1.0: ниже ищет смелее, выше строже"],
      ["center_anchor_confidence_threshold", english ? "Center confidence" : "Доверие к центру", english ? "0.0-1.0, blocks Start if the center is not confirmed" : "0.0-1.0: блокирует Start, если центр не подтвержден"],
      ["detailed_match_min_score", english ? "Detail check starts at" : "Детальная проверка от", english ? "Lower border for extra candidate verification" : "Нижняя граница дополнительной проверки кандидата"],
      ["detailed_match_max_score", english ? "Detail check ends at" : "Детальная проверка до", english ? "Upper border for extra candidate verification" : "Верхняя граница дополнительной проверки кандидата"],
    ];
  }
  if (tab === "timing") {
    return [
      ["screenshot_settle_seconds", english ? "Before screenshot" : "Перед скрином", english ? `${seconds}: after moving mouse to (0, 0)` : `${seconds}: после отвода мыши в (0, 0)`],
      ["pre_click_delay_seconds", english ? "Pause before node click" : "Пауза перед кликом по узлу", english ? `${seconds}: mouse stays parked at (0, 0), then moves to the node only for the click` : `${seconds}: мышь стоит на парковке (0, 0), потом выходит на узел только для клика`],
      ["click_hold_seconds", english ? "Node click hold" : "Удержание клика по узлу", english ? `${seconds}: mouse is on the node only while the left button is held` : `${seconds}: мышь на узле только пока зажата левая кнопка`],
      ["delay_between_clicks_seconds", english ? "Pause after node click" : "Пауза после клика по узлу", english ? `${seconds}: after the click, mouse is already parked at (0, 0)` : `${seconds}: после клика мышь уже убрана на парковку (0, 0)`],
      ["center_hold_seconds", english ? "Center click hold" : "Удержание клика в центр", english ? `${seconds}: hold center click while waiting for the buy-all animation` : `${seconds}: держим клик в центре, ждем анимацию покупки всего`],
      ["after_center_delay_seconds", english ? "Pause after center click" : "Пауза после клика в центр", english ? `${seconds}: mouse is parked; wait for the next Bloodweb and level-up` : `${seconds}: мышь на парковке; ждем новую паутину и прокачку уровня`],
      ["center_lost_timeout_seconds", english ? "Center loss timeout" : "Таймер потери центра", english ? `${seconds}: stop Start if the center does not return in time` : `${seconds}: остановить Start, если центр не вернулся за это время`],
    ];
  }
  return [
    ["mouse_check_interval_seconds", english ? "Mouse check interval" : "Интервал проверки мыши", english ? `${seconds}: how often manual movement is checked` : `${seconds}: как часто проверять ручное движение`],
    ["mouse_move_tolerance_pixels", english ? "Manual move tolerance" : "Допуск ручного сдвига", english ? "pixels: movement above this pauses the bot" : "пиксели: больший сдвиг ставит работу на паузу"],
  ];
}

function renderSettingsModal(): void {
  if (!state) return;
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    button.classList.toggle("active", (button as HTMLElement).dataset.settingsTab === settingsTab);
  });
  const body = $("settingsBody");
  const actions = $("settingsActions");
  actions.innerHTML = "";
  if (settingsTab === "general") {
    body.innerHTML = `
      <div class="switch-row">
        <div class="switch-copy">${t("alwaysOnTop")}<small>${t("savedInUiState")}</small></div>
        <label class="switch"><input id="settingsTopmost" type="checkbox" ${state.always_on_top ? "checked" : ""}><span class="slider"></span></label>
      </div>
      <label class="modal-field">
        <span>${t("language")}</span>
        <select id="settingsLanguage" class="setting-input">
          <option value="ru" ${lang() === "ru" ? "selected" : ""}>${t("russian")}</option>
          <option value="en" ${lang() === "en" ? "selected" : ""}>${t("english")}</option>
        </select>
      </label>
      <div class="setting-label">${t("version")}<small>${state.app_version ? `v${escapeHtml(state.app_version)}` : "dev"}</small></div>
      <button id="goLog" class="smallbtn">${t("goLog")}</button>
    `;
    $("settingsTopmost").addEventListener("change", (event) => {
      void window.bloodweb.setAlwaysOnTop((event.target as HTMLInputElement).checked).then(render).catch(showTransientError);
    });
    $("settingsLanguage").addEventListener("change", (event) => {
      void command("setLanguage", { language: (event.target as HTMLSelectElement).value });
    });
    $("goLog").addEventListener("click", () => {
      settingsTab = "log";
      renderSettingsModal();
    });
    return;
  }
  if (settingsTab === "log") {
    const logs = logViewCleared ? "" : escapeHtml((state.logs || []).join("\n"));
    body.innerHTML = `<div id="logPanel" class="log-panel">${logs || t("emptyLog")}</div>`;
    actions.innerHTML = `
      <button id="copyLog" class="smallbtn">${t("copyLog")}</button>
      <button id="clearLogView" class="smallbtn">${t("clearLog")}</button>
    `;
    $("copyLog").addEventListener("click", () => navigator.clipboard.writeText((state?.logs || []).join("\n")));
    $("clearLogView").addEventListener("click", () => {
      logViewCleared = true;
      renderSettingsModal();
    });
    return;
  }

  logViewCleared = false;
  const settings = state.settings || {};
  const fields = settingsTab === "recognition"
    ? [
      ["threshold", "Уровень доверия", "0.0-1.0"],
      ["detailed_match_min_score", "Детальная проверка от", "0.0-1.0"],
      ["detailed_match_max_score", "Детальная проверка до", "0.0-1.0"]
    ]
    : settingsTab === "timing"
      ? [
        ["pre_click_delay_seconds", "Перед каждым кликом", "секунды"],
        ["delay_between_clicks_seconds", "Между кликами", "секунды"],
        ["click_hold_seconds", "Удержание обычного клика", "секунды"],
        ["center_hold_seconds", "Удержание клика в центр", "секунды"],
        ["after_center_delay_seconds", "После клика в центр", "секунды"],
        ["screenshot_settle_seconds", "После отвода мыши", "секунды"]
      ]
      : [
        ["mouse_check_interval_seconds", "нтервал проверки движения", "секунды"],
        ["mouse_move_tolerance_pixels", "Допустимый сдвиг мыши", "пиксели"]
      ];
  fields.splice(0, fields.length, ...settingsFieldsForTab(settingsTab));
  const localizedFieldText: Record<string, [string, string]> = {
    threshold: [lang() === "en" ? "Confidence" : "Уровень доверия", "0.0-1.0"],
    detailed_match_min_score: [lang() === "en" ? "Detailed check from" : "Детальная проверка от", "0.0-1.0"],
    detailed_match_max_score: [lang() === "en" ? "Detailed check to" : "Детальная проверка до", "0.0-1.0"],
    pre_click_delay_seconds: [lang() === "en" ? "Before each click" : "Перед каждым кликом", lang() === "en" ? "seconds" : "секунды"],
    delay_between_clicks_seconds: [lang() === "en" ? "Between clicks" : "Между кликами", lang() === "en" ? "seconds" : "секунды"],
    click_hold_seconds: [lang() === "en" ? "Normal click hold" : "Удержание обычного клика", lang() === "en" ? "seconds" : "секунды"],
    center_hold_seconds: [lang() === "en" ? "Center click hold" : "Удержание клика в центр", lang() === "en" ? "seconds" : "секунды"],
    after_center_delay_seconds: [lang() === "en" ? "After center click" : "После клика в центр", lang() === "en" ? "seconds" : "секунды"],
    screenshot_settle_seconds: [lang() === "en" ? "After parking mouse" : "После отвода мыши", lang() === "en" ? "seconds" : "секунды"],
    mouse_check_interval_seconds: [lang() === "en" ? "Movement check interval" : "Интервал проверки движения", lang() === "en" ? "seconds" : "секунды"],
    mouse_move_tolerance_pixels: [lang() === "en" ? "Mouse movement tolerance" : "Допустимый сдвиг мыши", lang() === "en" ? "pixels" : "пиксели"],
    center_anchor_confidence_threshold: [lang() === "en" ? "Bloodweb center threshold" : "Порог центра Bloodweb", "0.0-1.0"],
  };
  for (const field of fields) {
    const text = localizedFieldText[field[0]];
    if (text && !field[1]) {
      field[1] = text[0];
      field[2] = text[1];
    }
  }
  if (settingsTab === "recognition" && !fields.some(([key]) => key === "center_anchor_confidence_threshold")) {
    fields.push(["center_anchor_confidence_threshold", "Порог центра Bloodweb", "0.0-1.0"]);
    const field = fields[fields.length - 1];
    const text = localizedFieldText.center_anchor_confidence_threshold;
    field[1] = text[0];
    field[2] = text[1];
  }
  body.innerHTML = `<div class="setting-grid">${fields.map(([key, label, note]) => `
    <label class="setting-label" for="set_${key}">${label}<small>${note}</small></label>
    <input id="set_${key}" class="setting-input" inputmode="decimal" value="${String(settings[key] ?? "")}">
  `).join("")}</div><div id="settingsError" class="error-line"></div>`;
  actions.innerHTML = `<button id="saveSettings" class="smallbtn">${t("save")}</button>`;
  $("saveSettings").addEventListener("click", () => saveSettings(fields.map(([key]) => key)));
}

function saveSettings(keys: string[]): void {
  const settings: Record<string, number> = {};
  for (const key of keys) {
    const raw = ($(`set_${key}`) as HTMLInputElement).value.replace(",", ".");
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      $("settingsError").textContent = t("numericError");
      return;
    }
    settings[key] = value;
  }
  if ("detailed_match_min_score" in settings && settings.detailed_match_min_score > settings.detailed_match_max_score) {
    $("settingsError").textContent = t("detailRangeError");
    return;
  }
  void command("saveSettings", { settings });
}

function showTransientError(message: unknown): void {
  const text = String(message).replace(/^Error:\s*/, "");
  $("runMessage").textContent = text;
  $("runStatus").textContent = "Ошибка";
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char] || char);
}

function bindEvents(): void {
  ensureSafetyDom();
  $("minButton").addEventListener("click", () => window.bloodweb.minimize());
  $("closeButton").addEventListener("click", () => window.bloodweb.close());
  $("pinButton").addEventListener("click", () => {
    if (!state) return;
    void window.bloodweb.setAlwaysOnTop(!state.always_on_top).then(render).catch(showTransientError);
  });
  $("gridButton").addEventListener("click", () => command("toggleGrid"));
  $("addCaptureButton").addEventListener("click", handleAddCaptureClick);
  $("centerButton").addEventListener("click", () => {
    void command("beginCenterSetup");
  });
  $("templatePicker").addEventListener("click", (event) => {
    event.stopPropagation();
    templateMenuOpen = !templateMenuOpen;
    renderTemplateDropdown();
  });
  $("templateCreate").addEventListener("click", () => openTemplateAction("create"));
  $("templateRename").addEventListener("click", () => openTemplateAction("rename"));
  $("templateDuplicate").addEventListener("click", () => openTemplateAction("duplicate"));
  $("templateDelete").addEventListener("click", () => openTemplateAction("delete"));
  $("priorityUp").addEventListener("click", () => {
    if (selectedPriorityIndex === null) return;
    const index = selectedPriorityIndex;
    selectedPriorityIndex = Math.max(0, index - 1);
    void command("reorderItem", { list: "priority", index, direction: -1 });
  });
  $("priorityDown").addEventListener("click", () => {
    if (!state || selectedPriorityIndex === null) return;
    const index = selectedPriorityIndex;
    selectedPriorityIndex = Math.min(state.priority_items.length - 1, index + 1);
    void command("reorderItem", { list: "priority", index, direction: 1 });
  });
  $("priorityToTemplate").addEventListener("click", () => {
    if (selectedPriorityIndex === null) return;
    const index = selectedPriorityIndex;
    selectedPriorityIndex = null;
    void command("moveItem", { source: "priority", target: "template", index });
  });
  $("priorityEdit").addEventListener("click", () => {
    if (selectedPriorityIndex === null) return;
    openItemEdit("priority", selectedPriorityIndex);
  });
  $("priorityRemove").addEventListener("click", () => {
    if (selectedPriorityIndex === null) return;
    openRemoveConfirm("priority", selectedPriorityIndex);
  });
  $("templateUp").addEventListener("click", () => {
    if (selectedTemplateIndex === null) return;
    const index = selectedTemplateIndex;
    selectedTemplateIndex = Math.max(0, index - 1);
    void command("reorderItem", { list: "template", index, direction: -1 });
  });
  $("templateDown").addEventListener("click", () => {
    if (!state || selectedTemplateIndex === null) return;
    const index = selectedTemplateIndex;
    selectedTemplateIndex = Math.min(state.template_items.length - 1, index + 1);
    void command("reorderItem", { list: "template", index, direction: 1 });
  });
  $("templateToPriority").addEventListener("click", () => {
    if (selectedTemplateIndex === null) return;
    const index = selectedTemplateIndex;
    selectedTemplateIndex = null;
    void command("moveItem", { source: "template", target: "priority", index });
  });
  $("templateEdit").addEventListener("click", () => {
    if (selectedTemplateIndex === null) return;
    openItemEdit("template", selectedTemplateIndex);
  });
  $("templateRemove").addEventListener("click", () => {
    if (selectedTemplateIndex === null) return;
    openRemoveConfirm("template", selectedTemplateIndex);
  });
  $("settingsButton").addEventListener("click", () => {
    openModal("settingsModal");
    renderSettingsModal();
  });
  $("tutorialButton").addEventListener("click", () => {
    openModal("tutorialModal");
  });
  $("testButton").addEventListener("click", () => command("testQueue"));
  $("startButton").addEventListener("click", () => command("start"));
  $("stopButton").addEventListener("click", () => command("stop"));
  $("safetyConsentCheck").addEventListener("change", (event) => {
    ($("safetyConsentContinue") as HTMLButtonElement).disabled = !(event.target as HTMLInputElement).checked;
  });
  $("safetyConsentClose").addEventListener("click", () => window.bloodweb.close());
  $("safetyConsentContinue").addEventListener("click", () => command("acceptSafetyConsent"));
  $("authorLink").addEventListener("click", () => window.bloodweb.openExternal("yt"));
  $("tgLink").addEventListener("click", () => window.bloodweb.openExternal("tg"));
  $("vkLink").addEventListener("click", () => window.bloodweb.openExternal("vk"));
  $("tutorialTgLink").addEventListener("click", () => window.bloodweb.openExternal("tg"));
  $("tutorialVkLink").addEventListener("click", () => window.bloodweb.openExternal("vk"));
  document.addEventListener("click", (event) => {
    const target = event.target as Node;
    if (!$("templateMenu").contains(target) && !$("templatePicker").contains(target)) {
      templateMenuOpen = false;
      renderTemplateDropdown();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      templateMenuOpen = false;
      renderTemplateDropdown();
      if (isOpen("templateActionModal")) closeModal("templateActionModal");
      if (isOpen("itemEditModal")) closeModal("itemEditModal");
      if (isOpen("removeConfirmModal")) closeModal("removeConfirmModal");
      if (isOpen("tutorialModal")) closeModal("tutorialModal");
      if (isOpen("centerSaveModal")) void command("cancelCenterAnchor");
      if (isOpen("referenceSaveModal")) void command("cancelReferenceCapture");
      activeItemEdit = null;
      activeRemoveItem = null;
    }
  });
  document.querySelectorAll<HTMLElement>("[data-close]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.close || "";
      closeModal(target);
      if (target === "itemEditModal") activeItemEdit = null;
      if (target === "removeConfirmModal") activeRemoveItem = null;
      if (target === "templateActionModal") activeTemplateAction = null;
      if (target === "centerSaveModal") void command("cancelCenterAnchor");
      if (target === "referenceSaveModal") void command("cancelReferenceCapture");
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-settings-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      settingsTab = button.dataset.settingsTab as typeof settingsTab;
      renderSettingsModal();
    });
  });
}

bindEvents();
window.bloodweb.onState((nextState: BotState) => render(nextState));
window.bloodweb.onError(showTransientError);
void command("getState");

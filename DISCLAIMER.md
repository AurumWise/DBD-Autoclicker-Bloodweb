# DISCLAIMER / ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ

**Автор / Author:** AurumWise  
**Официальный репозиторий / Official repository:**  
https://github.com/AurumWise/DBD-Autoclicker-Bloodweb

**Контакты / Contacts:**  
YouTube: https://www.youtube.com/@AurumWise  
VK: https://vk.com/aurumwise  
Telegram: https://t.me/AurumWise

> **Кратко / Short version:** DBD Autoclicker Bloodweb временно управляет курсором и может выполнять клики. Программа может ошибаться. Используйте её только под личным контролем. Если Вы не готовы принять риск ошибочного клика или последствия использования, не запускайте программу.

---

# РУССКАЯ ВЕРСИЯ

## 1. Назначение проекта

DBD Автокликер Bloodweb — неофициальный локальный инструмент автоматизации интерфейса. Он предназначен для визуального поиска похожих изображений на экране и выполнения обычных действий мышью по команде пользователя.

Проект может использоваться с Dead by Daylight как помощник для Bloodweb, однако технически он не привязан к одной игре и не является официальным продуктом какой-либо игры, платформы, издателя или разработчика.

## 2. Как работает программа

Программа работает только в пользовательской сессии компьютера и использует:

- локальные скриншоты экрана или его областей;
- локальное компьютерное зрение для сравнения изображений;
- пользовательскую сетку ROI;
- обычные перемещения курсора и клики мышью;
- локально сохранённые шаблоны, настройки и журналы.

Программа **не предназначена** для чтения памяти игры или другого ПО, внедрения DLL, обхода античита, изменения игровых файлов, доступа к игровым API, анализа игрового сетевого трафика, удалённого управления компьютером или скрытого сбора/передачи/продажи пользовательских данных.

## 3. Важное предупреждение о мыши и кликах

Программа может временно взять управление курсором: перемещать мышь и нажимать на элементы интерфейса.

Несмотря на предусмотренные защитные механизмы, программа может неверно распознать изображение, принять похожий объект за нужный, не найти нужный объект, сформировать неожиданную очередь, нажать не на тот элемент, остановиться, сработать медленнее или быстрее ожидаемого, либо перестать работать из-за подсказок, оверлеев, масштабирования, разрешения, обновлений игры или программных ошибок.

Пользователь обязан постоянно контролировать работу программы. Перед `Start` пользователь обязан проверить центр Bloodweb, положение сетки, выбранный шаблон, список приоритетов и тестовую очередь.

## 4. Защитные механизмы не являются гарантией

В программе могут использоваться:

- проверка визуального центра Bloodweb;
- блокировка автоклика при неподтверждённом центре;
- парковка курсора вне игровых элементов;
- остановка по ручному движению мыши;
- аварийная остановка по `F8` и кнопке `Stop`;
- тестовая очередь до запуска.

Эти механизмы снижают риск, но **не гарантируют**, что ошибочный клик никогда не произойдёт.

Главное правило:

```text
Нет подтверждённого центра Bloodweb — нет разрешения на новые автоклики.
```

Пользователь понимает и принимает, что программные сбои, внешние факторы, ошибки операционной системы, драйверов, устройств ввода, иных программ, игры, интерфейса или алгоритмов могут привести к нежелательному результату.

## 5. Полная ответственность пользователя

Используя программу, пользователь действует по собственной инициативе, на собственный риск и под собственную ответственность.

Пользователь самостоятельно отвечает за:

- совместимость программы со своим устройством, системой, играми и программами;
- точность настройки центра, сетки, ROI, шаблонов, приоритетов, таймингов и порогов;
- проверку очереди в режиме `Тест`;
- решение нажать `Start`;
- своевременное использование `F8`, `Stop` или ручного перехвата мыши;
- соблюдение правил игры, платформы, магазина, сервиса, античита и применимого законодательства;
- последствия любых кликов, ошибочных распознаваний, изменений в игре, ограничений учётной записи, блокировок, потери внутриигровых ресурсов, данных, времени или иных последствий.

## 6. Отказ от гарантий и ограничение ответственности

ПРОГРАММА ПРЕДОСТАВЛЯЕТСЯ «КАК ЕСТЬ» И «ПО МЕРЕ ДОСТУПНОСТИ».

AurumWise не гарантирует точность распознавания, отсутствие ошибок, безопасность каждого клика, совместимость с конкретной игрой, версией игры, платформой, обновлением, античитом, устройством, монитором, разрешением, DPI-масштабированием, оверлеем или программой; отсутствие потери прогресса, ресурсов, данных или доступа к сервисам; соответствие ожиданиям пользователя; постоянную доступность, поддержку, обновления или исправления.

В МАКСИМАЛЬНОЙ СТЕПЕНИ, ДОПУСТИМОЙ ПРИМЕНИМЫМ ПРАВОМ, AURUMWISE НЕ НЕСЁТ ОТВЕТСТВЕННОСТИ ЗА ЛЮБЫЕ УБЫТКИ, ПОТЕРИ, САНКЦИИ, ОГРАНИЧЕНИЯ, БЛОКИРОВКИ, ПОТЕРЮ ПРОГРЕССА, ВНУТРИИГРОВЫХ РЕСУРСОВ, АККАУНТА, ДАННЫХ, ДЕНЕГ, ВРЕМЕНИ, РЕПУТАЦИИ ИЛИ ИНЫЕ ПРЯМЫЕ, КОСВЕННЫЕ, СЛУЧАЙНЫЕ, СПЕЦИАЛЬНЫЕ ИЛИ ПОСЛЕДУЮЩИЕ ПОСЛЕДСТВИЯ, СВЯЗАННЫЕ С ИСПОЛЬЗОВАНИЕМ ИЛИ НЕВОЗМОЖНОСТЬЮ ИСПОЛЬЗОВАНИЯ ПРОГРАММЫ.

Если Вы не согласны с этим условием, не скачивайте, не запускайте и не используйте программу.

Ничто в этом документе не исключает или не ограничивает ответственность, которую нельзя исключить или ограничить по обязательному применимому праву.

## 7. Правила игр и платформ

Пользователь самостоятельно обязан проверить и соблюдать правила, условия использования, лицензионные соглашения, правила поведения, требования античита и иные условия каждой игры, платформы, магазина или сервиса, с которыми пользователь решает применять программу.

AurumWise не даёт обещаний, что использование программы разрешено правилами какой-либо игры, платформы, магазина, сервиса или античита. Пользователь сам принимает решение об использовании и несёт ответственность за его последствия.

## 8. Конфиденциальность, официальный источник и контакты

Официальная версия предназначена для локальной работы на компьютере пользователя. Если в официальной документации конкретной версии прямо не указано иное, скриншоты, шаблоны, настройки, журналы и рабочие данные остаются на устройстве пользователя. AurumWise не имеет удалённого доступа, не собирает, не продаёт, не передаёт и не разрешает третьим лицам собирать эти данные.

Официальный источник программы, кода, релизов и документации:

```text
https://github.com/AurumWise/DBD-Autoclicker-Bloodweb
```

Не используйте сторонние сборки, зеркала или модифицированные версии: их поведение, безопасность и обработка данных не контролируются AurumWise.

Контакты:  
YouTube: https://www.youtube.com/@AurumWise  
VK: https://vk.com/aurumwise  
Telegram: https://t.me/AurumWise

## 9. Неофициальный статус

DBD Autoclicker Bloodweb — независимый неофициальный проект. Он не аффилирован, не одобрен и не поддерживается разработчиками, издателями или правообладателями Dead by Daylight либо иных игр и сервисов.

Все товарные знаки, названия игр и материалы третьих лиц принадлежат их соответствующим правообладателям и упоминаются только для идентификации совместимости.

---

# ENGLISH VERSION

## 1. Purpose of the Project

DBD Autoclicker Bloodweb is an unofficial local interface-automation tool. It is designed to visually search for similar images on screen and perform ordinary mouse actions at the user’s command.

The project may be used with Dead by Daylight as a Bloodweb helper, but it is technically not tied to any single game and is not an official product of any game, platform, publisher, or developer.

## 2. How the Software Works

The Software operates only in the user’s local computer session and uses:

- local screenshots of the screen or screen areas;
- local computer vision to compare images;
- a user-configured ROI grid;
- ordinary cursor movement and mouse clicks;
- locally stored templates, settings, and logs.

The Software is **not intended** to read game memory or other software memory, inject DLLs, bypass anti-cheat, modify game files, access game APIs, inspect game network traffic, remotely control the user’s computer, or secretly collect, transfer, or sell user data.

## 3. Important Warning About Mouse Control and Clicks

The Software may temporarily control the cursor by moving the mouse and clicking interface elements.

Despite safety mechanisms, the Software may misidentify an image, mistake a similar object for a target, fail to find a target, produce an unexpected queue, click an unintended element, stop unexpectedly, operate more slowly or quickly than expected, or cease to function because of tooltips, overlays, scaling, resolution changes, game updates, or software errors.

The user must continuously supervise the Software. Before pressing `Start`, the user must check the Bloodweb center, grid placement, selected template, priority list, and test queue.

## 4. Safety Features Are Not a Guarantee

The Software may include visual Bloodweb-center verification, a block on autoclicking when the center is not confirmed, cursor parking away from game elements, stop-on-manual-mouse-movement, emergency stop by `F8` and the `Stop` button, and test-queue review before start.

These mechanisms reduce risk but **do not guarantee** that an unintended click will never occur.

```text
No confirmed Bloodweb center — no permission for new automated clicks.
```

The user understands and accepts that software faults, external conditions, operating-system behavior, drivers, input devices, other applications, the game, interface, or algorithms may still produce an undesired result.



## 5. User’s Sole Responsibility

By using the Software, the user acts voluntarily, at their own risk, and under their own responsibility.

The user is solely responsible for:

- compatibility with their device, operating system, games, and software;
- correct configuration of the center anchor, grid, ROI, templates, priorities, timings, and thresholds;
- reviewing the queue in `Test` mode;
- deciding to press `Start`;
- promptly using `F8`, `Stop`, or manually taking control of the mouse;
- compliance with game, platform, store, service, anti-cheat, and applicable-law requirements;
- consequences of inaccurate recognition, incorrect clicks, game changes, account restrictions, bans, loss of in-game resources, data, time, or any other outcome.

## 6. Disclaimer of Warranties and Limitation of Liability

THE SOFTWARE IS PROVIDED “AS IS” AND “AS AVAILABLE”.

AurumWise does not guarantee recognition accuracy, error-free operation, the safety of every click, compatibility with a particular game, game version, platform, update, anti-cheat system, device, monitor, resolution, DPI scaling, overlay, or application; the absence of loss of progress, resources, data, or service access; that the Software will meet the user’s expectations; or ongoing availability, support, updates, or fixes.

TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, AURUMWISE SHALL NOT BE LIABLE FOR ANY LOSS, DAMAGE, PENALTY, RESTRICTION, BAN, LOSS OF PROGRESS, IN-GAME RESOURCES, ACCOUNT ACCESS, DATA, MONEY, TIME, REPUTATION, OR ANY OTHER DIRECT, INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL RESULT ARISING FROM USE OF OR INABILITY TO USE THE SOFTWARE.

If you do not agree with this condition, do not download, run, or use the Software.

Nothing in this document excludes or limits liability that cannot be excluded or limited under mandatory applicable law.

## 7. Game and Platform Rules

The user is solely responsible for reviewing and complying with the rules, terms of use, license agreements, codes of conduct, anti-cheat requirements, and other conditions of every game, platform, store, or service with which the user chooses to use the Software.

AurumWise makes no representation that use of the Software is permitted by the rules of any game, platform, store, service, or anti-cheat system. The user makes the decision to use the Software and bears responsibility for its consequences.

## 8. Privacy, Official Source, and Contacts

The official release is designed to operate locally on the user’s computer. Unless official documentation for a particular version expressly states otherwise, screenshots, templates, settings, logs, and work data remain on the user’s device. AurumWise has no remote access to that data and does not collect, sell, transfer, or authorize third parties to collect that data.

The official source for the Software, source code, releases, and documentation is:

```text
https://github.com/AurumWise/DBD-Autoclicker-Bloodweb
```

Do not use third-party builds, mirrors, or modified versions: their behavior, security, and data handling are not controlled by AurumWise.

Contacts:  
YouTube: https://www.youtube.com/@AurumWise  
VK: https://vk.com/aurumwise  
Telegram: https://t.me/AurumWise

## 9. Unofficial Status

DBD Autoclicker Bloodweb is an independent unofficial project. It is not affiliated with, endorsed by, or supported by the developers, publishers, or rights holders of Dead by Daylight or any other games or services.

All trademarks, game names, and third-party materials belong to their respective owners and are mentioned solely to identify compatibility.

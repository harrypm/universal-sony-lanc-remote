# Prompt log - port LANC-USB-GUI to Qt6 / Python

Date: 2026-07-03
Working dir: /home/harry/LANC-USB-GUI

## User input (prompt)
"pull this, https://github.com/Novgorod/LANC-USB-GUI port it to QT6 and generic
python code rather then the Labview format."

## Commands run and outcomes

1. `git clone https://github.com/Novgorod/LANC-USB-GUI.git /home/harry/LANC-USB-GUI`
   - Cloned repo (71 objects). Contains `Arduino/arduino_lanc_nano-every.ino`,
     `GUI/serial_init.vi`, `GUI/serial_send.vi`, `GUI/Sony LANC remote.vi`,
     `README.md`, `LICENSE`.

2. Inspected README.md + Arduino sketch. Findings:
   - Arduino Nano Every LANC<->USB-serial at 115200 8N1.
   - Arduino -> PC: 8 raw bytes + 0x0A per LANC frame (~50/60 Hz).
   - PC -> Arduino: 4 ASCII hex chars (byte0+byte1) + line feed; repeats 4 frames.
   - GUI mimics RM-95: status/time-code monitoring, transport + camera buttons,
     EEPROM read/write, advanced dropdown, manual hex, fwd/rew held-seek.

3. `strings`/Python extraction on `Sony LANC remote.vi`:
   - VI block diagram is compressed/binary; only recoverable text was the title
     "Sony LANC remote GUI over serial" and sub-VI names. Exact button labels
     not recoverable. Functional spec taken from README + protocol references.

4. Environment check:
   - Python 3.10.12, PyQt6 6.11.0 present. pyserial missing.
   - `pip3 install --user pyserial` -> pyserial 3.5 installed.

5. Fetched canonical LANC protocol references (verified, not guessed):
   - http://www.boehmel.de/lanc.htm -> byte0 sub-commands, byte1 command tables,
     byte4 status, byte5 warnings/guide, byte6/7 counter/time-code/data-code.
   - L. Rosen Arduino LANC EEPROM docs (Hackster) -> service commands
     FF 00 read / 67 65 page+- / 38 36 addr+- / 34 30 data+- / 32 store;
     returned frame: page=byte4 hi-nibble, addr=byte6, data=byte7, ack=byte5
     (F0 read / F1 write).

6. Created port under `GUI_PyQt6/`:
   - `lanc_protocol.py` - command tables + frame decoders.
   - `lanc_serial_worker.py` - QThread serial worker (persistent loop, safe
     open/close, 8-byte-frame parser with embedded-0x0A self-heal).
   - `sony_lanc_remote.py` - PyQt6 main window + startup port dialog.
   - `requirements.txt`, `README.md`, `test_headless.py`.

7. Tests:
   - `python3 -m py_compile lanc_protocol.py lanc_serial_worker.py sony_lanc_remote.py`
     -> PY_COMPILE_OK.
   - `QT_QPA_PLATFORM=offscreen python3 test_headless.py` -> ALL CHECKS PASSED
     (14 checks: protocol decode of normal/warnings/counter/MM:SS/service frames,
     byte-stream parser ignores banner + self-heals embedded 0x0A, GUI labels
     update, service panel updates, manual-hex validation). 95 advanced commands
     populated.
   - PortDialog constructs and enumerates ports (found /dev/ttyACM0).

## Outputs / decisions
- Port kept separate in `GUI_PyQt6/`; original LabVIEW `.vi` files untouched.
- pyserial used for serial I/O (cross-platform, replaces NI-VISA).
- Frame reader accepts only 8-byte segments split on 0x0A so a data byte equal
  to 0x0A only drops that one frame and self-heals (50/60 Hz).
- byte4 status decode is best-effort; public docs table is incomplete, unknown
  cells fall back to raw hex.
- EEPROM/service commands use byte0=0xFF per L. Rosen docs.
- NOT validated against real hardware. All controls are user-interactable;
  real-world confirmation with the Arduino + LANC camera is required before
  relying on any command behaviour.

## Prompt follow-up: compact RM-95-style GUI redesign

User request:
"GUI looks like the first screenshot, I want the GUI to look like and more so
be compact as the shown remote gui image"

Actions:
- Read prior run output for `python3 sony_lanc_remote.py`:
  - confirmed earlier failure was path usage (`GUI_PyQt6/...` while already in
    `GUI_PyQt6/`), not app startup.
- Refactored `GUI_PyQt6/sony_lanc_remote.py` for a denser layout:
  - Added compact theme (smaller font, tighter margins, shorter buttons/inputs).
  - Reworked window layout to:
    - top row: **Keypad** + **Command** + **EEPROM**
    - middle row: **Transport** + **Camera**
    - lower row: **Status**
    - compact fixed-height **Log**
  - Added RM-95-style keypad section:
    - numeric/program keys 1..16 (0x00..0x1E),
    - Menu, Enter, +, -, and arrow navigation keys.
  - Tightened service and command groups and shortened warning text.
  - Reduced default window size and set a compact minimum size.

Validation commands:
- `python3 -m py_compile sony_lanc_remote.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED**.

### Second compactness pass (user: "Looking better but more work is needed")

Additional UI changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Further density reduction:
  - font 10 -> 9
  - button height 24 -> 22
  - log height 110 -> 74
  - tighter port width / paddings / window minimum size.
- Added one-row **Quick transport** icon strip (rew/pause/play/stop/rec/fwd/frame/eject).
- Reworked **Status** panel to compact boxed value fields with less empty space.
- Added **Exit** button in the command panel.
- Added RM-95-like EEPROM quick line:
  - `C:` 4-hex field (`FF00` default), `Get`, `Set`.
  - `Set` sends the exact 4-hex command.
- Updated live status label updates to value-only text to match boxed field style.

Validation re-run:
- `python3 -m py_compile sony_lanc_remote.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after this second pass.

### Bugfix pass: non-hold buttons not wired (clicked(bool) issue)

User-reported runtime error:
- Clicking buttons raised:
  `AttributeError: 'bool' object has no attribute 'upper'`
  at `_send()` from `_make_cmd_button` click lambda.

Root cause:
- `QPushButton.clicked` emits a boolean (`checked`).
- Non-hold button lambda was `lambda h=hex4, ...`, so the emitted bool replaced
  `h`, passing `True/False` to `_send()` instead of the hex string.

Fix:
- In `_make_cmd_button`, changed non-hold connection to:
  `b.clicked.connect(lambda _checked=False, h=hex4, l=label: self._send(h, note=l))`
  so the Qt bool is swallowed and command hex is preserved.

Regression coverage:
- Updated `GUI_PyQt6/test_headless.py` to emit `clicked(False)` on a non-hold
  button and assert sent command is still the expected hex (`1830`).

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** with the new click-path assertion.

### UX pass: Deck / Camera tabbed controls

User request:
- "I think it makes sence to have a Deck / Camara tabs with diffrent controls,
  this can make the GUI compacter"

Changes:
- Added `QTabWidget` control area in `GUI_PyQt6/sony_lanc_remote.py`.
- Replaced always-visible transport/camera rows with two tabs:
  - **Deck** tab: transport grid + quick icon strip
  - **Camera** tab: camera command grid
- This keeps one control set visible at a time, reducing visual clutter and
  improving compactness.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after tab refactor.

### UI fit/oversizing pass: text and box sizing

User request:
- "Fix text / box oversizing"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Reduced global compact sizing defaults:
  - font `9 -> 8`
  - button height `22 -> 20`
  - log height `74 -> 64`
  - window default/min sizes tightened.
- Reduced paddings for group boxes, buttons, and line-edit/combo controls.
- Reduced status value-box minimum width and made them size-policy based
  (`Expanding + Fixed`) to avoid oversized rigid boxes.
- Increased control-button width per row by changing transport/camera grids from
  5 columns to 4 columns (less text clipping).
- Shortened long labels that tended to clip:
  - `Store (NVRAM)` -> `Store` (tooltip keeps full meaning),
  - `Custom cmd (2 bytes hex)` -> `Custom cmd (2-byte hex)`.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after oversizing adjustments.

### UX correction pass: icon regression + oversized boxes in Deck tab

User feedback:
- "no this is the mess I am talking about"
- "you broke icons that were perfectly fine"
- "did not touch the boxes that are massive"

Fixes applied:
- Restored/standardized quick transport icons using native Qt media icons via
  `QToolButton` + `QStyle.StandardPixmap` (instead of fragile unicode glyph-only
  push buttons).
- Added shared signal wiring helper so icon buttons and text buttons use the
  same command/hold behavior.
- Reduced global UI sizing further (`font 8`, button height `20`, tighter
  paddings, smaller window defaults).
- Reduced oversized button growth:
  - text buttons now use minimum/fixed vertical policy with width caps.
  - transport/camera grids reset to 5 columns for better width balance.
- Kept keypad truly compact by overriding global button min-width for keypad
  buttons and menu/arrow keys.
- Reduced status value box minimum width and constrained them to fixed-height
  compact fields.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after icon + oversizing correction pass.

### Rollback pass: quick transport back to version from two changes earlier

User request:
- \"revent the quick trasport buttons to how they were 2 changes ago\"
- \"also make the text boxes less wide for outher controls\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Reverted quick transport strip to the earlier unicode-glyph button style:
  - `ICON_TRANSPORT` switched back from named icon keys + tooltips to
    `(\"glyph\", cmd, hold)` tuples (`⏪ ⏸ ▶ ⏹ ⏺ ⏩ ⏮ ⏭ ⏏`).
  - `_build_icon_strip()` now again builds buttons via `_make_cmd_button(...)`
    and applies compact width cap (`setMaximumWidth(36)`), matching the prior
    style from two UI changes earlier.
  - Removed temporary Qt-native icon plumbing imports (`QToolButton`, `QStyle`)
    that were only used by the newer icon implementation.
- Reduced text-box widths so other controls keep space:
  - Status value fields now use narrower min/max widths and mostly non-expanding
    policies, with only key long fields (`Latest frame`, `Warnings`, `Guide`)
    allowed to expand within tighter caps.
  - Command panel text widgets were constrained:
    - advanced command combo width capped (`160..280`),
    - custom hex input width capped (`110..210`).

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after quick-transport rollback + textbox width adjustments.

### Layout correction pass: jumbled spacing, off-center quick icons, deadspace in transport/camera/status fields

User feedback:
- \"spacing is now all jumbled\"
- \"icons are not centered\"
- \"text boxes still have 10pix + deadspace on width for transport/camera boxes\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Tightened global button horizontal padding (`0 3px -> 0 1px`) to reduce
  visual deadspace around labels.
- Transport/camera button geometry and layout made non-stretching:
  - `_make_cmd_button()` now uses fixed horizontal policy,
  - reduced width bounds (`min 40`, `max 120`),
  - transport/camera grids reduced spacing (`3 -> 2`) and aligned left/top to
    avoid distributed whitespace.
- Quick transport icon centering fixed while preserving glyph style:
  - `_build_icon_strip()` now creates dedicated fixed-size glyph buttons
    (`24 x COMPACT_BUTTON_H`) with zero padding, rather than inheriting larger
    command-button geometry.
  - row spacing reduced and row alignment forced left/vertical-center.
- Status field widths tightened again:
  - default status value box cap reduced (`max 140`),
  - `Latest frame` cap reduced (`max 260`),
  - `Warnings`/`Guide` caps reduced (`max 180`).

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after spacing + icon-centering pass.

### Command sub-box pass: make command input boxes smaller

User request:
- \"make the command sub-box input boxes smaller\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Reduced and fixed width for command dropdown input:
  - `adv_combo` width cap changed from `160..280` to `130..220`.
  - set fixed size policy so it no longer stretches.
- Reduced and fixed width for custom command hex input:
  - `hex_input` width cap changed from `80..130`.
  - set fixed size policy so it remains compact in the command panel grid.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after command input box size reduction.

### Command sub-box correction pass after screenshot: enforce visibly smaller inputs

User feedback:
- \"zero change as shown\" (screenshot indicated command controls still looked wide)

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Applied stronger, non-stretching command-panel layout changes:
  - Reduced command grid spacing (`3 -> 2`) and aligned controls to top-left.
  - Removed column-spanning placement for command inputs/buttons to prevent
    inherited column stretch from making inputs appear wide.
- Enforced strict fixed widths:
  - advanced command combo `setFixedWidth(150)` (instead of min/max caps),
  - custom hex input `setFixedWidth(92)`.
- Minor command-row cleanup to preserve compactness:
  - label shortened to `Custom cmd:`,
  - hex placeholder shortened to `e.g. 1834`.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after strict command-panel width enforcement.

### Command panel simplification pass: remove redundant labels and shrink inputs further

User feedback:
- \"Smaller...\"
- \"like there is unneeded 'command and custum cmd'\"
- \"The window context is already there\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Further reduced command input widths:
  - advanced command combo `setFixedWidth(132)` (from `150`),
  - custom hex input `setFixedWidth(74)` (from `92`).
- Removed redundant command-row labels to reduce clutter:
  - dropped visible `Command:` and `Custom cmd:` row labels,
  - kept section context via `Command` group box title and control tooltips.
- Kept command row compact and non-stretching:
  - top row now: `[advanced combo] [Send] [Exit]`,
  - second row now: `[hex input] [Send]`,
  - alignment remains top-left with compact grid spacing.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after removing redundant labels and further downsizing command inputs.

### Compaction fix pass: window would not compact smaller

User feedback:
- \"the window will not compact\" (with screenshots showing persistent wide layout)

Diagnosis:
- Window compaction was still constrained by:
  - high explicit minimum size (`820 x 470`),
  - top-row weighted stretch allocation across `Keypad/Command/EEPROM`,
  - long port combo display text contributing to top-bar width pressure.

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Lowered explicit minimum/default window size:
  - `resize(940, 530) -> resize(880, 510)`
  - `setMinimumSize(820, 470) -> setMinimumSize(640, 400)`
- Removed forced proportional stretching in top row:
  - replaced weighted `addWidget(..., 3/4/3)` with natural-size `addWidget(...)`
    and a trailing `addStretch(1)` so extra width goes to empty space rather
    than being forced inside each group box.
- Constrained port combo width behavior so long serial descriptions no longer
  force large top-bar width:
  - fixed width range (`120..220`), fixed size policy,
  - `AdjustToMinimumContentsLengthWithIcon` + `minimumContentsLength(12)`.
- Shortened displayed port entries in the main toolbar:
  - combo now shows only device path (`/dev/...`) while storing device data;
  - full `device - description` remains available as per-item tooltip.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after compaction constraint fixes.

### Default window resolution pass: match screenshot resolution

User request:
- \"make the resolution of the screenshot deafult\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Updated startup window size to match the screenshot resolution:
  - `self.resize(880, 510) -> self.resize(767, 514)`.
- Kept compact resize floor unchanged:
  - `self.setMinimumSize(640, 400)`.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after default resolution update.

### UI pass: move log to separate tab + enlarge/center quick transport icons

User request:
- \"move log to a seprate tab, make quick trasport icons centred within there boxs and make them 8pix bigger overall\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Log moved into its own tab:
  - control tabs are now `Deck`, `Camera`, `Log`,
  - removed standalone bottom log panel from the main layout.
- Added dedicated log-tab builder:
  - `_build_log_tab()` now owns `self.log` and provides an expanding log editor
    inside the `Log` tab.
- Quick transport icon buttons updated:
  - increased button size by +8 px overall (`24x20 -> 32x28`),
  - explicit larger icon font (`COMPACT_FONT_PT + 2`),
  - style enforces centered glyph rendering (`padding:0; text-align:center;`).

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after log-tab and quick-icon updates.

### UI correction pass: dead-space cleanup + quick transport icon visibility/centering

User feedback:
- \"fix dead space, icons did nto cahnge for the quick trasport butttons\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Reduced dead space in transport/camera controls:
  - command buttons now use content-based widths (`fontMetrics`) instead of
    broad fixed width caps, so short labels no longer sit in oversized buttons.
  - transport/camera group boxes are now fixed-size to content and aligned
    top-left in tab pages.
- Reduced dead space in Deck/Camera tab layouts:
  - deck/camera page layouts explicitly align to top-left to avoid stretched
    placement artifacts.
- Quick transport icons made visibly larger and centered:
  - icon button size increased again to `40 x 36`,
  - icon font size increased (`COMPACT_FONT_PT + 6`),
  - glyph centering enforced via style + zero content margins.
  - quick transport group also set to fixed-size to content.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after dead-space cleanup and quick-icon visibility changes.

### Rollback pass: revert latest dead-space/icon tweak

User request:
- \"revent changes, you ignored context\"

Rollback applied in `GUI_PyQt6/sony_lanc_remote.py`:
- Reverted the immediate prior dead-space/icon pass while keeping earlier
  approved updates (including log tab and default resolution) intact.
- Restored button sizing logic for transport/camera controls from content-based
  fixed widths back to the prior min/max button sizing.
- Restored quick transport sizing/styling from `40 x 36` / larger font back to
  prior state (`32 x 28`, `COMPACT_FONT_PT + 2`, prior row spacing/stretch).
- Removed the extra fixed-size constraints and forced top-left alignment hooks
  added in that last pass for transport/camera/quick-transport groups/pages.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after rollback.

### Stock-size update pass: set default window size to latest screenshot

User request:
- \"change window size to size of screenshot as stock size\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Updated startup/default window size:
  - `self.resize(767, 514) -> self.resize(767, 473)`.
- Kept minimum size unchanged:
  - `self.setMinimumSize(640, 400)`.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after stock-size update.

### UI style pass: move box titles above border to prevent inline squashing

User request:
- \"move box name text above instead of in-line to prevent squashing\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Updated global `QGroupBox` styling so titles render in the top margin area
  rather than overlapping the frame line:
  - `QGroupBox margin-top: 0.4em -> 1.0em`
  - `QGroupBox::title` now uses:
    - `subcontrol-origin: margin`
    - `subcontrol-position: top left`
    - `top: 0px` (instead of negative offset on the border line)

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after box-title positioning change.

### Keypad style pass: match attached screenshot look

User request:
- \"change keypad to this style as attached screenshot\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Added keypad-specific group styling:
  - `QGroupBox#keypadGroup` now uses a classic light-gray panel look with a
    subtle border and small radius.
  - keypad title color set dark for contrast on light background.
- Added keypad-specific button styling using Qt dynamic properties:
  - `QPushButton[keypadClassic=\"true\"]` gives light-gray button faces, border,
    and red label text (classic keypad style).
  - pressed-state darkening added.
  - `keypadNeutral` property used for neutral keys (`Enter`, `+`, `-`) so they
    render dark text while number/menu/arrow keys stay red.
- Applied keypad properties and tighter keypad grid spacing/margins in
  `_build_keypad_group()`:
  - group object name set to `keypadGroup`,
  - keypad buttons tagged with `keypadClassic`,
  - neutral-key overrides applied where needed.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after keypad restyling.

### Keypad correction pass: revert contrast change and apply layout-focused keypad tuning

User feedback:
- \"so you ignored the layout and messed with contrast...\"

Changes in `GUI_PyQt6/sony_lanc_remote.py`:
- Reverted keypad contrast overrides:
  - removed `QGroupBox#keypadGroup` light-background overrides,
  - removed `QPushButton[keypadClassic]` / `keypadNeutral` style rules and the
    per-button dynamic-property tagging.
- Applied layout-focused keypad refinement only:
  - keypad grid remains compact with left/top alignment,
  - numeric keys set to tighter fixed sizes for consistent two-row matrix,
  - function row (`Menu`, `Enter`, `+`, `-`) kept as four equal wide buttons,
  - directional row reordered to a clearer D-pad-like sequence:
    `←`, `↓`, `→`, `↑`,
  - row button sizing unified to avoid uneven spacing.

Validation:
- `python3 -m py_compile sony_lanc_remote.py test_headless.py lanc_serial_worker.py lanc_protocol.py`
- `QT_QPA_PLATFORM=offscreen python3 test_headless.py`
  - Result: **ALL CHECKS PASSED** after keypad contrast rollback + layout-focused update.

### CI/CD pass: add cross-platform self-contained binary GitHub Actions workflow (MISRC-style)

User request:
- \"add gh actions workflow, mirror what MISRC has for making self contained binary releases cross platform\"

Changes:
- Added workflow file:
  - `.github/workflows/build.yml`
- Workflow structure mirrors MISRC release flow pattern:
  - triggers: `workflow_dispatch` (with `create_release` + `release_tag`),
    PR events, and tag pushes (`v*`),
  - artifact build jobs for Linux/Windows/macOS,
  - release job gated on tag push or manual dispatch with release flag.
- Packaging adapted to this Python/PyQt project:
  - Linux: PyInstaller `--onefile` binary zipped,
  - Windows: PyInstaller `--onefile` EXE zipped,
  - macOS: PyInstaller `.app` bundle zipped.
- Release publishing:
  - downloads build artifacts and publishes them via
    `softprops/action-gh-release@v3` using resolved release tag logic modeled
    after MISRC’s workflow.

Validation:
- Workflow YAML parse check:
  - `ruby -e 'require \"yaml\"; YAML.load_file(\".github/workflows/build.yml\"); puts \"YAML_OK\"'`
  - Result: `YAML_OK`

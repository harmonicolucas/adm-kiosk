# ADM Kiosk — Navegador Digital Signage para Android TV

Aplicação **Android TV / Smart TV** que funciona como um **navegador dedicado em modo Kiosk**
(digital signage). Arranca automaticamente com o dispositivo, abre uma página web previamente
configurada, permanece em ecrã completo, impede o acesso ao ambiente Android e adapta-se
automaticamente às diferentes resoluções (HD, Full HD, 2K, 4K, projectores).

A interface está desenhada com a **identidade visual dos Aeroportos de Moçambique (ADM)** —
estilo dos painéis de informação ao público (FIDS): fundo azul-marinho, azul de aviação e
acentos em dourado/âmbar, com a barra tricolor de Moçambique (verde / dourado / vermelho).

> **Logótipo:** o emblema em `app/src/main/res/drawable/ic_adm_mark.xml` é uma interpretação
> vetorial (o manual de marca oficial da ADM não é público). Para usar o logótipo oficial,
> substitua esse ficheiro (ou coloque um `logo_adm.png` em `res/drawable-nodpi/` e aponte
> `R.drawable.ic_adm_mark` para ele em `AdmBranding.kt` / `KioskOverlay.kt`). As cores estão
> centralizadas em `res/values/colors.xml` e `ui/theme/Color.kt`.

---

## 1. Requisitos

- Android Studio (Koala ou superior)
- JDK 17
- Android SDK 34
- Dispositivo/TV com **Android 5.0 (API 21)** ou superior

## 2. Compilar

```bash
# Gerar o Gradle wrapper (uma vez), se o gradle-wrapper.jar não existir:
gradle wrapper --gradle-version 8.9

# Debug
./gradlew assembleDebug        # Windows: gradlew.bat assembleDebug

# Release (assine com a sua keystore)
./gradlew assembleRelease
```

O APK fica em `app/build/outputs/apk/`.

> Nota: o binário `gradle/wrapper/gradle-wrapper.jar` não é incluído no repositório. Abra o
> projeto no Android Studio (que o gera automaticamente) ou execute `gradle wrapper`.

## 3. Instalar / testar

```bash
adb connect <IP_DA_TV>:5555
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

**Código de acesso por omissão: `0000`** — altere-o de imediato na área de administração.

Abrir a administração a partir do ecrã de apresentação:
- Comando/teclado: tecla **MENU**, ou
- Prima **BACK (voltar) 4 vezes** em menos de 2,5 s.

---

## 4. Modo Kiosk real (Device Owner)

Sem Device Owner a app usa *screen pinning* + ocultação da UI (bom, mas o utilizador ainda pode
sair com algum esforço). Para um **Kiosk verdadeiro** (barra de estado desativada, HOME
bloqueado, sem saída), provisione a app como **Device Owner**. Isto exige um dispositivo **sem
nenhuma conta Google configurada** (reset de fábrica ou novo).

```bash
# Instale a app primeiro e depois:
adb shell dpm set-device-owner com.adm.kiosk/.kiosk.DeviceOwnerReceiver
```

Se obtiver sucesso, ao arrancar a app aplica as políticas (`applyDeviceOwnerPolicies()`):
- Whitelist de Lock Task para o próprio pacote;
- App definida como **HOME** persistente;
- Barra de estado e keyguard desativados;
- Restrições `no_safe_boot` e `no_factory_reset`.

Para **sair para manutenção**: administração → *Sair do modo Kiosk* (pede confirmação e liberta
as políticas). Para remover totalmente o Device Owner via ADB:

```bash
adb shell dpm remove-active-admin com.adm.kiosk/.kiosk.DeviceOwnerReceiver
```

### Provisionamento em massa
Também pode provisionar por **QR code / NFC** durante o setup do dispositivo, apontando para o
componente `com.adm.kiosk/.kiosk.DeviceOwnerReceiver` e o APK. Ver documentação Android
Enterprise (`android.app.extra.PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME`).

---

## 5. Funcionalidades

| Requisito | Implementação |
|---|---|
| Gestão de links (nome, URL, categoria) | `AdminScreen` + Room (`WebLink`, `WebLinkDao`) |
| Código de acesso 4 dígitos | `PinScreen` + `PinCrypto` (SHA-256 salgado) + limite de tentativas |
| Navegador dedicado full-screen | `KioskActivity` + `WebViewFactory` |
| Actualização automática / recarregar | `scheduleAutoRefresh` + intervalo configurável |
| Recuperação de rede | `NetworkMonitor` + `scheduleRetry` |
| Ocultar barras do Android | Immersive sticky + tema fullscreen |
| Modo Kiosk / Lock Task | `KioskManager` (Device Owner + `startLockTask`) |
| Arranque automático | `BootReceiver` (BOOT_COMPLETED) |
| Ajuste a qualquer ecrã | `ScreenMetrics` + `useWideViewPort` + zoom por escala |
| Recuperar última configuração | `SettingsRepository` (DataStore) |
| Segurança da área admin | PIN, lockout de 30 s, sem exposição do código |

## 6. Arquitectura

```
com.adm.kiosk
├── data/            Room (links) + DataStore (settings) + repositórios
├── security/        PinCrypto (hash salgado do PIN)
├── kiosk/           KioskManager, DeviceOwnerReceiver, BootReceiver
├── web/             WebViewFactory (WebView configurado para signage)
├── util/            NetworkMonitor, ScreenMetrics
└── ui/
    ├── theme/       Paleta e tema ADM (Compose)
    ├── components/  Cabeçalho e barra tricolor ADM
    ├── kiosk/       KioskActivity + overlays de estado
    └── admin/       PIN + painel de administração
```

Camadas MVVM (ViewModel + Repository) e armazenamento local desacoplado, prontos para uma futura
**gestão remota** (sincronização de links/configuração via servidor, dashboard central,
monitorização online/offline, agendamento de conteúdos e vários ecrãs) — basta adicionar uma
fonte de dados remota por trás de `LinkRepository`/`SettingsRepository`.

## 7. Configuração recomendada

- Ligar **Modo Kiosk (Lock Task)** e provisionar Device Owner.
- Definir a **página inicial** (estrela) no link pretendido.
- Ajustar **Zoom** conforme a resolução (ex.: 4K → 150–200%).
- Definir **intervalo de actualização** e **atraso de nova tentativa**.
- Alterar o **código de acesso** para um valor não trivial.

## Autor

Harmónico Lucas  
[harmonicolucas@gmail.com](mailto:harmonicolucas@gmail.com)


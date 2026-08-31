## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Naya Create protocol constants."""

# USB identifiers
NAYA_VID   = 0x37D1
PID_LEFT   = 0x0064
PID_RIGHT  = 0x00C8
PID_DONGLE = 0x012C

PID_NAMES = {
  PID_LEFT:   "Create Left",
  PID_RIGHT:  "Create Right",
  PID_DONGLE: "Dongle",
}

# Serial configuration
BAUD_RATE = 115200

# Protocol addressing
SOURCE_HOST = 0xAA
DEST_LEFT   = 0x50
DEST_RIGHT  = 0x51
DEST_DONGLE = 0x50  # dongle uses same address as left

SIDE_DEST = {
  "left":   DEST_LEFT,
  "right":  DEST_RIGHT,
  "dongle": DEST_DONGLE,
}

# Message framing
EOT = 0x04

# --- Command categories ---

CAT_REMAP      = 0x30
CAT_BLE        = 0xBE
CAT_IC_CHARGER = 0xCA
CAT_MODULE     = 0xDE
CAT_LED        = 0xED
CAT_RESET      = 0xEE
CAT_FIRMWARE   = 0xF1
CAT_FLASH      = 0xFA
CAT_SYSTEM     = 0xFE
CAT_META       = 0xFF

CAT_NAMES = {
  CAT_REMAP:      "REMAP",
  CAT_BLE:        "BLE",
  CAT_IC_CHARGER: "IC_CHARGER",
  CAT_MODULE:     "MODULE",
  CAT_LED:        "LED",
  CAT_RESET:      "RESET",
  CAT_FIRMWARE:   "FIRMWARE",
  CAT_FLASH:      "FLASH",
  CAT_SYSTEM:     "SYSTEM",
  CAT_META:       "META",
}

# --- System commands (0xFE) ---

SYS_MEDIA_ID_REQUEST        = 0x1001
SYS_GET_FW_VERSION          = 0x1002
SYS_MODULE_BATTERY_RECOVERY = 0x1003
SYS_GET_HW_ID_NUMBER        = 0x1004
SYS_SET_HOST_OS             = 0x1005
SYS_GET_KB_BATTERY_LEVEL    = 0x1006
SYS_SET_RELEASE_MODE        = 0x1007
SYS_TOGGLE_KEYSCAN_MODE     = 0x1008
SYS_KEYSCAN_EVENT           = 0x1009

SYS_NAMES = {
  SYS_MEDIA_ID_REQUEST:        "MEDIA_ID_REQUEST",
  SYS_GET_FW_VERSION:          "GET_FW_VERSION",
  SYS_MODULE_BATTERY_RECOVERY: "MODULE_BATTERY_RECOVERY",
  SYS_GET_HW_ID_NUMBER:        "GET_HW_ID_NUMBER",
  SYS_SET_HOST_OS:             "SET_HOST_OS",
  SYS_GET_KB_BATTERY_LEVEL:    "GET_KB_BATTERY_LEVEL",
  SYS_SET_RELEASE_MODE:        "SET_RELEASE_MODE",
  SYS_TOGGLE_KEYSCAN_MODE:     "TOGGLE_KEYSCAN_MODE",
  SYS_KEYSCAN_EVENT:           "KEYSCAN_EVENT",
}

# --- Module commands (0xDE) ---

MOD_SEND_HANDSHAKE      = 0x1001
MOD_DETECT              = 0x1002
MOD_CHECK_HANDSHAKE     = 0x1003
MOD_FWUP                = 0x1005
MOD_RESET               = 0x1006
MOD_GET_ADDRESS         = 0x1007
MOD_GET_FW_VERSION      = 0x1008
MOD_GET_BATTERY         = 0x1009
MOD_FILE_FW_VERSION     = 0x100A
MOD_GET_PRECISE_BATTERY = 0x100B

MOD_NAMES = {
  MOD_SEND_HANDSHAKE:      "SEND_HANDSHAKE",
  MOD_DETECT:              "MODULE_DETECT",
  MOD_CHECK_HANDSHAKE:     "CHECK_HANDSHAKE",
  MOD_FWUP:                "MODULE_FWUP",
  MOD_RESET:               "RESET_MODULE",
  MOD_GET_ADDRESS:         "GET_ADDRESS",
  MOD_GET_FW_VERSION:      "GET_MODULE_FW_VERSION",
  MOD_GET_BATTERY:         "GET_BATTERY",
  MOD_FILE_FW_VERSION:     "MODULE_FILE_FW_VERSION",
  MOD_GET_PRECISE_BATTERY: "GET_PRECISE_BATTERY",
}

MODULE_TYPES = {
  0: "None",
  1: "Touch",
  2: "Track",
  3: "Tune",
  4: "Float",
  5: "Query",
}

# --- BLE commands (0xBE) ---

BLE_SET_PAIR_ADDRESS      = 0x1001
BLE_GET_PAIR_ADDRESS      = 0x1002
BLE_UNPAIR_ADDRESS        = 0x1003
BLE_UNPAIR_ALL            = 0x1004
BLE_GET_ALL_PAIRS         = 0x1005
BLE_GET_NAME              = 0x1006
BLE_SET_NAME              = 0x1007
BLE_GET_ADDRESS           = 0x1008
BLE_SELECT_PROFILE        = 0x1009
BLE_CLEAR_PROFILE         = 0x100A
BLE_SELECT_OUT            = 0x100B
BLE_GET_STATUS            = 0x100C
BLE_GET_DONGLE_ADDR       = 0x100D
BLE_GET_SLOTX_ADDR        = 0x100E
BLE_GET_FW_VERSION        = 0x100F
BLE_CLEAR_ALL_SPLIT_LINKS = 0x1010

BLE_NAMES = {
  BLE_SET_PAIR_ADDRESS:      "SET_PAIR_ADDRESS",
  BLE_GET_PAIR_ADDRESS:      "GET_PAIR_ADDRESS",
  BLE_UNPAIR_ADDRESS:        "UNPAIR_ADDRESS",
  BLE_UNPAIR_ALL:            "UNPAIR_ALL",
  BLE_GET_ALL_PAIRS:         "GET_ALL_PAIRS",
  BLE_GET_NAME:              "GET_BLE_NAME",
  BLE_SET_NAME:              "SET_BLE_NAME",
  BLE_GET_ADDRESS:           "GET_BLE_ADDRESS",
  BLE_SELECT_PROFILE:        "SELECT_BLE_PROFILE",
  BLE_CLEAR_PROFILE:         "CLEAR_BLE_PROFILE",
  BLE_SELECT_OUT:            "SELECT_BLE_OUT",
  BLE_GET_STATUS:            "GET_BLE_STATUS",
  BLE_GET_DONGLE_ADDR:       "GET_DONGLE_ADDR",
  BLE_GET_SLOTX_ADDR:        "GET_SLOTX_ADDR",
  BLE_GET_FW_VERSION:        "GET_BLE_FW_VERSION",
  BLE_CLEAR_ALL_SPLIT_LINKS: "CLEAR_ALL_SPLIT_LINKS",
}

# --- LED commands (0xED) ---

LED_ON                = 0x1003
LED_OFF               = 0x1004
LED_TOGGLE            = 0x1005
LED_INCREMENT         = 0x1006
LED_DECREMENT         = 0x1007
LED_ADJUST_BRIGHTNESS = 0x1008
LED_RED               = 0x1009
LED_GREEN             = 0x100A
LED_BLUE              = 0x100B
LED_WHITE             = 0x100C
LED_EFFECT_CYCLE      = 0x100D
LED_HUE_SATURATION    = 0x100E
LED_HALT              = 0x100F
LED_RESUME            = 0x1010
LED_SELECT_EFFECT     = 0x1011
LED_RGB_BRIGHTNESS    = 0x1050
LED_FORCE_ON          = 0x10D1
LED_FORCE_OFF         = 0x10D2

LED_NAMES = {
  LED_ON:                "LEDs_ON",
  LED_OFF:               "LEDs_OFF",
  LED_TOGGLE:            "LEDs_TOGGLE",
  LED_INCREMENT:         "LEDs_INCREMENT",
  LED_DECREMENT:         "LEDs_DECREMENT",
  LED_ADJUST_BRIGHTNESS: "LED_ADJUST_BRIGHTNESS",
  LED_RED:               "LEDs_RED",
  LED_GREEN:             "LEDs_GREEN",
  LED_BLUE:              "LEDs_BLUE",
  LED_WHITE:             "LEDs_WHITE",
  LED_EFFECT_CYCLE:      "LEDs_EFFECT_CYCLE",
  LED_HUE_SATURATION:    "LEDs_HUE_SATURATION",
  LED_HALT:              "LEDs_HALT",
  LED_RESUME:            "LEDs_RESUME",
  LED_SELECT_EFFECT:     "SELECT_LEDs_EFFECT",
  LED_RGB_BRIGHTNESS:    "LEDs_RGB_BRIGHTNESS",
  LED_FORCE_ON:          "FORCE_LEDs_ON",
  LED_FORCE_OFF:         "FORCE_LEDs_OFF",
}

# --- Reset commands (0xEE) ---

RESET_MCU_BOOT = 0x10AE
RESET_DFU      = 0x10BE
RESET_NORMAL   = 0x10CE

# --- Flash commands (0xFA) ---

FLASH_TEST             = 0x1001
FLASH_FORMAT_PARTITION = 0x1002
FLASH_ERASE_CHIP       = 0x1006

# --- Meta commands (0xFF) ---

META_WAIT                = 0x1000
META_VERIFY_FLASH        = 0x1001
META_ENQUEUE_READ_LAYERS = 0x1002
META_GET_MODULE_INFO     = 0x1003

# --- Subcmd name lookup by category ---

SUBCMD_NAMES = {
  CAT_SYSTEM: SYS_NAMES,
  CAT_MODULE: MOD_NAMES,
  CAT_BLE:    BLE_NAMES,
  CAT_LED:    LED_NAMES,
}

def subcmd_name(category: int, subcmd: int) -> str:
  names = SUBCMD_NAMES.get(category, {})
  name = names.get(subcmd)
  if name:
    return name
  cat_name = CAT_NAMES.get(category, f"0x{category:02x}")
  return f"{cat_name}/0x{subcmd:04x}"

# --- Safety: dangerous commands ---

DANGEROUS_COMMANDS = {
  (CAT_RESET, RESET_MCU_BOOT):         "MCU_BOOT_RESET",
  (CAT_RESET, RESET_DFU):              "DFU_RESET",
  (CAT_RESET, RESET_NORMAL):           "NORMAL_RESET",
  (CAT_FLASH, FLASH_FORMAT_PARTITION): "FORMAT_PARTITION",
  (CAT_FLASH, FLASH_ERASE_CHIP):       "ERASE_CHIP",
}

DANGEROUS_TEXT_COMMANDS = {"clear_bonds", "mcuboot_reset"}

# --- ZMQ ---

ZMQ_CORE_PUB_PORT_KEY = "ZMQ_CORE_PUB_PORT_SHARED_MEM"
ZMQ_FLOW_PUB_PORT_KEY = "ZMQ_FLOW_PUB_PORT_SHARED_MEM"

ZMQ_TOPIC_COMMAND     = "command"
ZMQ_TOPIC_DEVICE_LIST = "stream:device_list"
ZMQ_TOPIC_OP_STATUS   = "stream:operation_status_normal"
ZMQ_TOPIC_FW_UPDATE   = "stream:fw_update_status"
ZMQ_TOPIC_OP_FWUPDATE = "stream:operation_status_fwupdate"

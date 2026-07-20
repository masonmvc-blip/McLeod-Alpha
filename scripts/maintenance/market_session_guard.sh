#!/usr/bin/env bash

# Returns success only outside the live entry window unless explicitly overridden.
mcleod_market_change_allowed() {
  if [[ "${MCLEOD_ALLOW_MARKET_HOURS_CHANGES:-0}" == "1" ]]; then
    return 0
  fi

  local session
  session="$(TZ=America/New_York date '+%u %H%M')"
  local weekday="${session%% *}"
  local clock="${session##* }"
  [[ "$weekday" -lt 6 && "$clock" -ge 0930 && "$clock" -lt 1545 ]] && return 1
  return 0
}

mcleod_market_change_block_message() {
  echo "market_change_freeze=ACTIVE et=$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Set MCLEOD_ALLOW_MARKET_HOURS_CHANGES=1 only after the bot is safely stopped."
}
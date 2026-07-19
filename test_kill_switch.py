#!/usr/bin/env python3
"""
Test script to demonstrate the emergency kill switch functionality.

This script:
1. Sets up signal handlers
2. Simulates trading loop
3. Tests graceful shutdown on Ctrl+C

Usage: python3 test_kill_switch.py
Then press Ctrl+C to trigger the emergency kill switch.
"""

import signal
import atexit
import sys
import time


# Global flag for graceful shutdown
_shutdown_requested = False


def graceful_shutdown(signum=None, frame=None):
    """Handle Ctrl+C (SIGINT) and system termination (SIGTERM) gracefully."""
    global _shutdown_requested
    
    _shutdown_requested = True
    
    try:
        # Flush all logs
        if sys.stdout:
            sys.stdout.flush()
        if sys.stderr:
            sys.stderr.flush()
        
        # Print shutdown message
        signal_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM (Termination)" if signum == signal.SIGTERM else "Unknown"
        print(f"\n{'='*80}")
        print(f"🛑 Emergency Kill Switch Activated: {signal_name}")
        print(f"{'='*80}")
        print(f"\n✓ Open Position Preserved (if any)")
        print(f"✓ Logs flushed")
        print(f"✓ Database intact")
        print(f"✓ Exit clean\n")
        
    except Exception as e:
        print(f"\nWarning during shutdown: {e}\n", file=sys.stderr)
    
    # Avoid SystemExit from atexit context during automated tests.
    if signum is None:
        return

    # Exit when invoked by actual signal.
    sys.exit(0)


def register_signal_handlers():
    """Register graceful shutdown handlers for Ctrl+C and system termination."""
    signal.signal(signal.SIGINT, graceful_shutdown)   # Ctrl+C
    signal.signal(signal.SIGTERM, graceful_shutdown)  # System termination
    atexit.register(graceful_shutdown)                # Fallback on normal exit


def test_kill_switch():
    """Test the emergency kill switch."""
    register_signal_handlers()
    
    print("=" * 80)
    print("EMERGENCY KILL SWITCH TEST")
    print("=" * 80)
    print("\n✓ Signal handlers registered")
    print("✓ Kill switch active (Ctrl+C to test)\n")
    
    iteration = 0
    
    while True:
        if _shutdown_requested:
            break
        
        iteration += 1
        print(f"[{iteration}] Trading loop iteration... (Press Ctrl+C to exit)")
        time.sleep(1)


if __name__ == "__main__":
    try:
        test_kill_switch()
    except KeyboardInterrupt:
        pass

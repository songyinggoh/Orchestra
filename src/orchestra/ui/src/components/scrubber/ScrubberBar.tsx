/**
 * Time-travel scrubber. Sits below CostBar on RunDetailPage.
 *
 * Responsibilities:
 *  - Slider over 0..events.length-1 with a thumb at the selected index.
 *  - Play/Pause that advances the selection every (1000 / playbackRate) ms.
 *  - Jump-to-latest ('.') button + keyboard shortcut.
 *  - Event ticks colored by event type. Checkpoints render as diamonds,
 *    security events render 2x-height pink bars (see Scrubtick).
 *  - Live-head indicator: pulsing accent tick at the latest sequence.
 *  - Keyboard: ← / → step by 1; Home / End jump to ends; Space play/pause; '.' live.
 *
 * The URL `/runs/:id/@:sequence` is the source of truth for selectedSequence —
 * RunDetailPage owns the navigate() call on every change.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Play, Pause, SkipForward } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { useUIStore } from '../../stores/useUIStore';
import { useShortcuts } from '../../lib/shortcuts';
import type { AnyEvent } from '../../types/events';
import { Scrubtick } from './Scrubtick';

interface ScrubberBarProps {
  events: AnyEvent[];
  /** null = pinned to live head (latest sequence). */
  selectedSequence: number | null;
  onSequenceChange: (sequence: number | null) => void;
  /** When true, scrubber bar is always visible even if no events yet. */
  alwaysVisible?: boolean;
}

export function ScrubberBar({
  events,
  selectedSequence,
  onSequenceChange,
  alwaysVisible = false,
}: ScrubberBarProps) {
  const playbackRate = useUIStore((s) => s.playbackRate);
  const [isPlaying, setIsPlaying] = useState(false);

  const max = Math.max(0, events.length - 1);
  const liveHead = max;
  const currentIndex = selectedSequence ?? liveHead;
  const atLive = selectedSequence === null || selectedSequence >= liveHead;

  // Playback timer. setState inside the async setInterval callback is not
  // a synchronous-in-effect render — so it doesn't trip the cascading-
  // renders rule.
  useEffect(() => {
    if (!isPlaying || currentIndex >= liveHead) return;
    const interval = Math.max(50, Math.round(1000 / Math.max(1, playbackRate)));
    const id = window.setInterval(() => {
      const next = currentIndex + 1;
      if (next >= liveHead) {
        onSequenceChange(null);
        setIsPlaying(false);
      } else {
        onSequenceChange(next);
      }
    }, interval);
    return () => window.clearInterval(id);
  }, [isPlaying, currentIndex, liveHead, playbackRate, onSequenceChange]);

  const step = useCallback(
    (delta: number) => {
      const next = Math.min(liveHead, Math.max(0, currentIndex + delta));
      onSequenceChange(next >= liveHead ? null : next);
    },
    [currentIndex, liveHead, onSequenceChange],
  );

  const jumpToLatest = useCallback(() => {
    onSequenceChange(null);
    setIsPlaying(false);
  }, [onSequenceChange]);

  const togglePlay = useCallback(() => {
    setIsPlaying((p) => {
      // Starting from the head wouldn't advance — short-circuit to avoid an
      // isPlaying=true state with no effect.
      if (!p && currentIndex >= liveHead) return false;
      return !p;
    });
  }, [currentIndex, liveHead]);

  const shortcutMap = useMemo(
    () => ({
      ArrowLeft: (e: KeyboardEvent) => {
        e.preventDefault();
        step(-1);
      },
      ArrowRight: (e: KeyboardEvent) => {
        e.preventDefault();
        step(1);
      },
      Home: (e: KeyboardEvent) => {
        e.preventDefault();
        onSequenceChange(0);
      },
      End: (e: KeyboardEvent) => {
        e.preventDefault();
        jumpToLatest();
      },
      ' ': (e: KeyboardEvent) => {
        e.preventDefault();
        togglePlay();
      },
      '.': (e: KeyboardEvent) => {
        e.preventDefault();
        jumpToLatest();
      },
    }),
    [step, onSequenceChange, jumpToLatest, togglePlay],
  );
  useShortcuts(shortcutMap, events.length > 0);

  if (!alwaysVisible && events.length === 0) return null;

  const activeEvent = events[currentIndex];
  const valueText = activeEvent
    ? `event ${currentIndex + 1} of ${events.length}, type ${activeEvent.event_type}`
    : `event 0 of 0`;

  return (
    <div
      className="border-b border-zinc-800 bg-zinc-900/80 px-4 py-2"
      data-testid="scrubber-bar"
    >
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={isPlaying ? 'Pause playback' : 'Play back events'}
          disabled={events.length <= 1}
          onClick={togglePlay}
        >
          {isPlaying ? <Pause size={14} /> : <Play size={14} />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label="Jump to latest event"
          disabled={atLive}
          onClick={jumpToLatest}
        >
          <SkipForward size={14} />
        </Button>

        <div className="relative flex-1">
          <Slider
            min={0}
            max={max}
            step={1}
            value={[currentIndex]}
            onValueChange={([next]) => {
              const clamped = Math.min(liveHead, Math.max(0, next));
              onSequenceChange(clamped >= liveHead ? null : clamped);
            }}
            aria-label="Event sequence"
            aria-valuetext={valueText}
            aria-valuemin={0}
            aria-valuemax={max}
            aria-valuenow={currentIndex}
            className="z-10"
          />
          {/* Radix's Slider.Thumb doesn't forward aria-valuetext from the Root
              props, so mirror the announcement via a live region so screen
              readers describe the event under the cursor. */}
          <span
            className="sr-only"
            role="status"
            aria-live="polite"
            aria-valuetext={valueText}
          >
            {valueText}
          </span>
          <div className="pointer-events-none absolute inset-x-0 top-1/2 h-0 -translate-y-1/2">
            {events.map((ev, i) => {
              const pct = max === 0 ? 0 : (i / max) * 100;
              return (
                <Scrubtick
                  key={ev.event_id}
                  eventType={ev.event_type}
                  sequence={ev.sequence}
                  xPercent={pct}
                  isSelected={i === currentIndex}
                />
              );
            })}
            {events.length > 0 && (
              <motion.div
                aria-hidden
                className="absolute top-1/2 rounded-full bg-[var(--accent)]"
                style={{
                  left: 'calc(100% - 3px)',
                  width: 6,
                  height: 6,
                  transform: 'translateY(-50%)',
                }}
                animate={atLive ? { opacity: [0.4, 1, 0.4] } : { opacity: 0.6 }}
                transition={
                  atLive
                    ? { duration: 1.4, repeat: Infinity, ease: 'easeInOut' }
                    : { duration: 0 }
                }
              />
            )}
          </div>
        </div>

        <div className="min-w-[7.5rem] text-right font-mono text-[11px] tabular-nums text-zinc-500">
          {events.length === 0
            ? '—'
            : atLive
              ? `live · ${events.length}`
              : `${currentIndex + 1} / ${events.length}`}
        </div>
      </div>
    </div>
  );
}

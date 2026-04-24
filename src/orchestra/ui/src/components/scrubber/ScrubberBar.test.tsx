import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ScrubberBar } from './ScrubberBar';
import { useUIStore } from '../../stores/useUIStore';
import type { AnyEvent, EventType } from '../../types/events';

function makeEvents(count: number): AnyEvent[] {
  const types: EventType[] = [
    'execution.started',
    'node.started',
    'state.updated',
    'node.completed',
    'checkpoint.created',
    'security.violation',
    'execution.completed',
  ];
  return Array.from({ length: count }, (_, i) => {
    const event_type = types[i % types.length] as EventType;
    const base = {
      event_id: `e${i}`,
      run_id: 'r1',
      sequence: i,
      timestamp: new Date(1700000000000 + i * 1000).toISOString(),
      schema_version: 1,
    };
    // Fill event-type specific fields with plausible defaults; the component
    // does not inspect them, so minimal shaping is OK.
    return { ...base, event_type, node_id: 'n1' } as unknown as AnyEvent;
  });
}

describe('ScrubberBar', () => {
  beforeEach(() => {
    useUIStore.setState({ playbackRate: 2, selectedSequence: null });
  });

  it('renders ticks for every event and a live-mode indicator', () => {
    const events = makeEvents(12);
    render(
      <ScrubberBar
        events={events}
        selectedSequence={null}
        onSequenceChange={() => {}}
      />,
    );
    // One tick per event.
    const ticks = screen.getAllByLabelText(/event \d+ /);
    expect(ticks.length).toBe(events.length);
    // In live mode the counter shows "live · N".
    expect(screen.getByText(/live · 12/)).toBeInTheDocument();
  });

  it('advances the selected sequence on ArrowRight', async () => {
    const events = makeEvents(30);
    const onChange = vi.fn();
    render(
      <ScrubberBar
        events={events}
        selectedSequence={5}
        onSequenceChange={onChange}
      />,
    );

    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith(6);
  });

  it('steps back on ArrowLeft', () => {
    const events = makeEvents(30);
    const onChange = vi.fn();
    render(
      <ScrubberBar
        events={events}
        selectedSequence={10}
        onSequenceChange={onChange}
      />,
    );

    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(onChange).toHaveBeenCalledWith(9);
  });

  it("jumps to live head on '.'", () => {
    const events = makeEvents(30);
    const onChange = vi.fn();
    render(
      <ScrubberBar
        events={events}
        selectedSequence={5}
        onSequenceChange={onChange}
      />,
    );

    fireEvent.keyDown(window, { key: '.' });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('jumps to the first event on Home', () => {
    const events = makeEvents(30);
    const onChange = vi.fn();
    render(
      <ScrubberBar
        events={events}
        selectedSequence={15}
        onSequenceChange={onChange}
      />,
    );

    fireEvent.keyDown(window, { key: 'Home' });
    expect(onChange).toHaveBeenCalledWith(0);
  });

  it('ignores shortcuts while focus is in an editable element', async () => {
    const events = makeEvents(10);
    const onChange = vi.fn();
    render(
      <>
        <input data-testid="in" />
        <ScrubberBar
          events={events}
          selectedSequence={3}
          onSequenceChange={onChange}
        />
      </>,
    );
    const input = screen.getByTestId('in') as HTMLInputElement;
    input.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('clamps ArrowRight at live head (does not overflow)', () => {
    const events = makeEvents(5);
    const onChange = vi.fn();
    render(
      <ScrubberBar
        events={events}
        selectedSequence={4}
        onSequenceChange={onChange}
      />,
    );

    fireEvent.keyDown(window, { key: 'ArrowRight' });
    // At live head already → null (pin-to-live).
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('reports the active event type via aria-valuetext', () => {
    const events = makeEvents(8);
    render(
      <ScrubberBar
        events={events}
        selectedSequence={3}
        onSequenceChange={() => {}}
      />,
    );
    const live = screen.getByRole('status');
    expect(live.textContent).toContain('event 4 of 8');
    expect(live.textContent).toContain(events[3].event_type);
  });
});

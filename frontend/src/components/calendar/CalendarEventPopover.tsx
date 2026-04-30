import { startTransition, useEffect, useState } from 'react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import type { CalendarEvent } from '@/lib/types';
import { useCancelEnrollment, useDeleteUnavailability, useEnrollOffering } from '@/lib/mutations';

export function CalendarEventPopover({
  kidId,
  event,
  open,
  onClose,
}: {
  kidId: number;
  event: CalendarEvent | null;
  open: boolean;
  onClose: () => void;
}) {
  const cancel = useCancelEnrollment();
  const del = useDeleteUnavailability();
  const enroll = useEnrollOffering();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inFlight = cancel.isPending || del.isPending || enroll.isPending;

  // Reset mutation + error state whenever the selected event changes.
  // event.id is the only stable signal; mutation refs are recreated each render.
  useEffect(() => {
    startTransition(() => {
      setErrorMsg(null);
    });
    cancel.reset();
    del.reset();
    enroll.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event?.id]);

  const handleCancel = () => {
    if (!event?.enrollment_id) return;
    setErrorMsg(null);
    cancel.mutate(
      { kidId, enrollmentId: event.enrollment_id },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(err.message || 'Failed to cancel enrollment'),
      },
    );
  };

  const handleEnroll = () => {
    if (!event?.offering_id) return;
    setErrorMsg(null);
    enroll.mutate(
      { kidId, offeringId: event.offering_id },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(err.message || 'Failed to enroll'),
      },
    );
  };

  const handleDelete = () => {
    if (!event?.block_id) return;
    setErrorMsg(null);
    del.mutate(
      { kidId, blockId: event.block_id },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(err.message || 'Failed to delete block'),
      },
    );
  };

  const isMatch = event?.kind === 'match';
  const isEnrollment = event?.kind === 'enrollment';
  const isLinkedBlock =
    event?.kind === 'unavailability' && event.from_enrollment_id != null;

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        // Suppress user-initiated dismiss while a mutation is in-flight.
        if (inFlight && !o) return;
        if (!o) onClose();
      }}
    >
      <SheetContent>
        {event && (
          <>
            <SheetHeader>
              <SheetTitle>{event.title}</SheetTitle>
              <SheetDescription>
                {event.all_day
                  ? 'All day'
                  : `${event.time_start?.slice(0, 5)}–${event.time_end?.slice(0, 5)}`}
                {isMatch && event.score != null && (
                  <span className="ml-2 text-xs">Score: {event.score.toFixed(2)}</span>
                )}
              </SheetDescription>
            </SheetHeader>

            {errorMsg && (
              <div className="mt-4">
                <ErrorBanner message={errorMsg} />
              </div>
            )}

            <div className="mt-6 flex gap-2 items-center">
              {isMatch && (
                <>
                  <Button onClick={handleEnroll} disabled={inFlight}>
                    Enroll
                  </Button>
                  {event.registration_url && (
                    <a
                      href={event.registration_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-muted-foreground underline self-center"
                    >
                      View details ↗
                    </a>
                  )}
                </>
              )}
              {isEnrollment && (
                <Button onClick={handleCancel} disabled={inFlight} variant="destructive">
                  Cancel enrollment
                </Button>
              )}
              {!isMatch && !isEnrollment && !isLinkedBlock && (
                <Button onClick={handleDelete} disabled={inFlight} variant="destructive">
                  Delete block
                </Button>
              )}
              {isLinkedBlock && (
                <p className="text-xs text-muted-foreground">
                  This block was created by your enrollment. Cancel the enrollment to remove it.
                </p>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

"use client";

// A button that opens a confirmation dialog (shadcn/ui AlertDialog) and runs
// the action when the user confirms. Cancel, Escape, and focus return come
// from the Radix dialog.

import type { ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

type Props = {
  label: ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
};

export function ConfirmAction({ label, title, description, confirmLabel, destructive, disabled, onConfirm }: Props) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant={destructive ? "outline" : "default"} size="sm" disabled={disabled}>
          {label}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant={destructive ? "destructive" : "default"} onClick={onConfirm}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

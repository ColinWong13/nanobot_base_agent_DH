import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/**
 * The design system's contract, in one file.
 *
 * Shape is the cheapest thing to check and the easiest to drift, so it is
 * checked here rather than left to review: a button that quietly goes back to a
 * 12px corner is a bug nobody files. Each assertion names the role a control
 * plays, so a failure says which role moved rather than which class changed.
 *
 * The radii these classes resolve to live in globals.css and are snapped to
 * MD3's own steps (4/8/12/16/24/28/32). This file checks the *mapping* from
 * component to step; the values themselves are the token layer's business.
 */
describe("UI shape system", () => {
  it("makes every button a pill, and a text field a filled box", () => {
    render(
      <>
        <Button>Continue</Button>
        <Input aria-label="Name" />
        <Textarea aria-label="Description" />
      </>,
    );

    // MD3 buttons are fully rounded at every size.
    expect(screen.getByRole("button", { name: "Continue" })).toHaveClass("rounded-full");

    // MD3 filled text fields round the top corners and square the bottom ones.
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveClass("rounded-t-compact", "rounded-b-none");
    expect(screen.getByRole("textbox", { name: "Description" })).toHaveClass(
      "rounded-t-compact",
      "rounded-b-none",
    );
  });

  it("gives dialogs a larger step than panels, so a modal is not a panel", () => {
    const dialog = render(
      <Dialog open>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Edit name</DialogTitle>
          <DialogDescription>Choose a new name.</DialogDescription>
        </DialogContent>
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Edit name" })).toHaveClass("rounded-modal");
    dialog.unmount();

    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogTitle>Delete item?</AlertDialogTitle>
          <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
        </AlertDialogContent>
      </AlertDialog>,
    );
    expect(screen.getByRole("alertdialog", { name: "Delete item?" })).toHaveClass(
      "rounded-modal",
    );
  });

  it("keeps floating surfaces and their items on the shared radius scale", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>Open menu</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Rename</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    expect(screen.getByRole("menu")).toHaveClass("rounded-floating");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveClass(
      "rounded-control",
    );
  });

  it("lifts a floating surface with a token, never a hand-written shadow", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>Open menu</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Rename</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    // The shadow colour lives inside --elevation-*, which is what lets one
    // class be correct in both themes. A raw shadow-[...] here would mean a
    // parallel dark: override somewhere below it.
    expect(screen.getByRole("menu")).toHaveClass("shadow-elevation-2");
  });
});

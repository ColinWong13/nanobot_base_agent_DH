/**
 * `cytoscape-fcose` ships no type declarations of its own.
 *
 * It is an extension rather than a library: importing it registers an `fcose`
 * layout on whichever cytoscape instance the caller passes, which is exactly
 * what `cytoscape.Ext` describes. Saying that here is more honest than typing
 * it as `any`, and it means `cytoscape.use(fcose)` type-checks for the right
 * reason.
 */
declare module "cytoscape-fcose" {
  import type cytoscape from "cytoscape";

  /**
   * The `fcose` layout's parameters.
   *
   * cytoscape's own `LayoutOptions` is a closed union of the layouts it ships
   * with, and an extension's options cannot be added to a union the way an
   * interface can be augmented — so they are declared here instead.
   *
   * They are named rather than cast away because `FcoseLayoutOptions` extends
   * `BaseLayoutOptions`, which makes it assignable to `LayoutOptions` on its
   * own. Build the options as a typed value before handing them to cytoscape
   * and no cast is needed: an object literal written inline would be rejected
   * for having properties the union does not know, but a value of a type that
   * extends a member of the union is accepted, and every parameter below is
   * still checked.
   */
  export interface FcoseLayoutOptions extends cytoscape.BaseLayoutOptions {
    name: "fcose";
    animate?: boolean;
    /** Higher spreads nodes further apart; the knob for a crowded graph. */
    nodeSeparation?: number;
    idealEdgeLength?: number;
    /** How hard the layout pulls disconnected pieces toward the centre. */
    gravity?: number;
    /** Iterations of the spectral pass that seeds node positions. */
    numIter?: number;
    quality?: "draft" | "default" | "proof";
    randomize?: boolean;
    /** Draw a tiling to keep unconnected nodes from stacking on each other. */
    packComponents?: boolean;
  }

  const extension: cytoscape.Ext;
  export default extension;
}

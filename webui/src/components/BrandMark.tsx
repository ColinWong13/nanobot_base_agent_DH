/**
 * The PRA mark: an organic droplet.
 *
 * Inline SVG rather than an <img> so the fill can be currentColor. A droplet
 * is the shape, but a symmetric one reads as a water drop on a plumbing
 * sign -- the long asymmetric shoulder is what makes it organic, and it is
 * also what keeps it legible at 24px, where the tail still has enough mass
 * to read as a sweep rather than a speck.
 *
 * public/brand/pra_mark.svg carries the same path for the three places that
 * cannot be a component: the favicon, the PWA manifest, and the websocket
 * channel icon that lives inside the Python package. The path is duplicated
 * rather than shared because both halves would need a build step to share
 * it, and this file and that one are each other's only consumer. Change one,
 * change the other.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 50 50"
      className={className}
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      {/* translate centres the droplet inside the 50x50 viewBox. The path's
          bounding box is 36.86 x 42 and sits at x 10.14..47, y 5..47, so the
          box needs shifting by 3.572 left and 1 up to land on (25,25).
          Worth stating exactly: the control points reach x=47 and overshoot
          the curve, so eyeballing the numbers gets the centring wrong by
          about half a unit, and the shape is asymmetric enough that the
          error shows as the tail drifting off-centre. */}
      <g transform="translate(-3.572,-1)">
        <path d="M16 5C21 11 26 15 32 16C41.5 17.5 47 24.5 47 33C47 41 40 47 31 47C21 47 12.5 40 10.5 30C9 21 12.5 11 16 5Z" />
      </g>
    </svg>
  );
}

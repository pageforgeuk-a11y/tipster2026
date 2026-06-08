---
name: Vibrant Matchday System
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#3e4851'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#6e7882'
  outline-variant: '#bdc8d2'
  surface-tint: '#006492'
  primary: '#006492'
  on-primary: '#ffffff'
  primary-container: '#00b2ff'
  on-primary-container: '#004161'
  inverse-primary: '#8bceff'
  secondary: '#b70b3d'
  on-secondary: '#ffffff'
  secondary-container: '#da2f54'
  on-secondary-container: '#fffbff'
  tertiary: '#7212ff'
  on-tertiary: '#ffffff'
  tertiary-container: '#b596ff'
  on-tertiary-container: '#4b00b0'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#c9e6ff'
  primary-fixed-dim: '#8bceff'
  on-primary-fixed: '#001e2f'
  on-primary-fixed-variant: '#004b6f'
  secondary-fixed: '#ffdadb'
  secondary-fixed-dim: '#ffb2b8'
  on-secondary-fixed: '#40000f'
  on-secondary-fixed-variant: '#91002d'
  tertiary-fixed: '#e9ddff'
  tertiary-fixed-dim: '#d1bcff'
  on-tertiary-fixed: '#23005b'
  on-tertiary-fixed-variant: '#5700c9'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Montserrat
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Montserrat
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Montserrat
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.05em
  headline-lg-mobile:
    fontFamily: Montserrat
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 0.5rem
  sm: 1rem
  md: 1.5rem
  lg: 2.5rem
  xl: 4rem
  gutter: 1rem
  margin-mobile: 1rem
  margin-desktop: 2.5rem
---

## Brand & Style

The design system moves away from aggressive, dark aesthetics toward a **Bright, Energetic, and Professional** experience. It is designed for the modern sports fan who values clarity and speed. The personality is optimistic and high-performance, capturing the excitement of a matchday under clear skies.

The visual style is a hybrid of **Modern Corporate and Glassmorphism**. It utilizes airy whitespace, semi-transparent layered surfaces, and vibrant color pops to create a sense of depth without the weight of heavy shadows. The interface should feel like a premium digital broadcast—fluid, translucent, and sophisticated.

## Colors

The palette is anchored by a dominant **Sky Blue** (#00B2FF), representing the energy of the pitch and clear day games. 

- **Primary (Sky Blue):** Used for key actions, brand elements, and primary focus areas.
- **Secondary (Coral Punch):** A high-vibrancy accent used sparingly for notifications, live indicators, and critical call-to-actions to provide a warm contrast to the cool primary blue.
- **Surface & Backgrounds:** We use **Clean White** (#FFFFFF) for primary cards and **Light Slate Gray** (#F8FAFC) for page backgrounds to maintain a "breathable" feel.
- **Accents:** A deep violet/purple is used for secondary data points and decorative gradients to add depth to the glassmorphic layers.

## Typography

This design system uses a dual-font approach to balance impact with legibility. 

**Montserrat** is used for all headlines and display text. Its geometric construction feels athletic and modern, providing the necessary "punch" for scores and titles. 

**Inter** is the workhorse for body copy, data tables, and labels. It ensures high readability at small sizes, which is critical for complex sports statistics and fantasy rosters. Type is generally set in high-contrast dark slate (#1E293B) against the light backgrounds to ensure accessibility.

## Layout & Spacing

The layout follows a **Fluid Grid** philosophy with a 12-column structure for desktop and a 4-column structure for mobile. 

- **Vertical Rhythm:** Built on a 4px baseline grid.
- **Margins:** Generous 40px (2.5rem) side margins on desktop create an airy, premium feel. Mobile margins are tighter at 16px (1rem) to maximize data density.
- **Density:** We prioritize a "comfortable" density for news and articles, but a "compact" density for statistics tables and player lists to minimize scrolling during active match windows.

## Elevation & Depth

Hierarchy is established through **Glassmorphism and Tonal Layering** rather than heavy shadows.

1.  **Level 0 (Base):** Light Gray (#F8FAFC) solid background.
2.  **Level 1 (Cards):** Pure White (#FFFFFF) with a 1px subtle border (#E2E8F0) and a very soft, high-diffusion shadow (8% opacity).
3.  **Level 2 (Overlays):** Glassmorphic surfaces with a `backdrop-filter: blur(12px)` and `background: rgba(255, 255, 255, 0.7)`. These should have a subtle "inner glow" white stroke on the top edge to simulate light hitting the glass.
4.  **Level 3 (Interactive):** Elements that are being hovered or dragged gain a Sky Blue tinted glow shadow to indicate activity.

## Shapes

The shape language is **Rounded and Friendly**. 

Standard containers and cards use a 16px (1rem) corner radius to soften the interface. Smaller components like input fields use 8px (0.5rem). High-action items, such as "Live" tags or primary CTA buttons, utilize a full pill-shape (circular ends) to stand out against the more architectural grid of the cards.

## Components

- **Buttons:** Primary buttons are Sky Blue with white text and a pill-shaped radius. They should have a subtle gradient (top-to-bottom) for a slight tactile feel.
- **Cards:** White or semi-transparent glass backgrounds. Use thin 1px borders (#E2E8F0). Headlines inside cards should be Montserrat SemiBold.
- **Chips & Tags:** Use tinted backgrounds (e.g., 10% opacity Sky Blue with 100% opacity Blue text). For "Live" status, use Coral Punch with a pulse animation.
- **Input Fields:** Soft gray backgrounds (#F1F5F9) with no border until focused. On focus, use a 2px Sky Blue stroke.
- **Player Lists:** Use clean alternating row highlights in very faint gray. Avatars should be circular with a white border to "pop" off the background.
- **Progress Bars:** Use a gradient from Tertiary (Purple) to Primary (Blue) to represent completion or statistics, mirroring the energetic visual language of the brand.
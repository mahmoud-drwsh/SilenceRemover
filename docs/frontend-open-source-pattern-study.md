# Frontend open-source pattern study

Research date: 2026-09-07

## Scope

This study extracts interaction and design-system patterns from primary open-source implementations that resemble Media Manager's canonical video cards, linked variants, designer revisions, audio review queue, virtual views, uploads, and mobile use. It does not recommend copying source code, visual assets, trademarks, or product-specific styling.

## Recommended direction

Keep the existing web stack unless a separate engineering assessment finds a concrete blocker. Rebuild the interface as a componentized application shell with one canonical media-card model and two responsive presentations:

- **Card grid** for browsing pipeline finals. A canonical card owns its original, no-overlay video, active designer video, designer revision history, and subtitle actions.
- **Compact review rows** for the audio Todo and Approved queues, where title review and approval state matter more than a large preview.
- **Virtual views** as route-addressable filters, not folders. Keep All, Needs Designer, Pipeline Final, No Overlay, Designer Video, Pending, Trash, Audio Todo, and Audio Approved.
- **Contextual action bars** for selection and review actions. Keep destructive actions visually and structurally separate from routine actions.
- **Persistent upload status** so designer uploads survive navigation and expose queued, uploading, success, duplicate, and failed states with retry.

## Source patterns to adapt

### 1. Immich: canonical asset interaction and durable uploads

Immich's thumbnail component makes the whole thumbnail keyboard-focusable, exposes selection state, supports Enter to open, a keyboard selection shortcut, a visible focus ring, and long-press selection for coarse pointers. It deliberately suppresses hover-only behavior on touch devices. Adapt that split for Media Manager: tap opens a canonical card, long press enters selection, and every hover action must also be available by keyboard and through the card menu. [Immich thumbnail source](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/lib/components/assets/thumbnail/Thumbnail.svelte)

Immich changes its selection-bar wording at the small breakpoint while retaining the same action context. Adapt this as a sticky contextual bar: desktop shows “N selected”; narrow screens show the count and only the most important actions, with the rest in an overflow menu. [Immich selection bar](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/lib/components/timeline/AssetSelectControlBar.svelte)

Its asset viewer has a small set of immediate actions, an overflow menu for the long tail, horizontal overflow protection, explicit loading status, keyboard Escape navigation, and owner-gated destructive actions. Apply the same hierarchy to a card detail surface: preview, download active variant, upload designer revision, and info are primary; history and uncommon maintenance actions belong in overflow. [Immich viewer action bar](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/lib/components/asset-viewer/AssetViewerNavBar.svelte)

Immich keeps upload work in a persistent, minimizable panel. Each upload has explicit pending, in-progress, duplicate, success, and failure states; failures are individually retryable, and completion produces summarized notifications. Adapt this for designer revisions so leaving the card does not hide an in-progress upload or its failure. [Immich upload panel](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/routes/UploadPanel.svelte), [upload item states](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/routes/UploadAssetPreview.svelte)

Immich models related assets as a stack with one primary asset and exposes deliberate “set primary” and “unstack” actions. Media Manager should borrow the primary-plus-related mental model, but name the relationships with domain terms: active designer video plus immutable designer revision history, never a generic “stack.” [Immich stack operations](https://github.com/immich-app/immich/blob/4c7b30c18b55e74224ad1a223a2058ea4a13cc1f/web/src/lib/utils/asset-utils.ts)

### 2. PeerTube: workflow filters and operational lists

PeerTube's management screen uses a reusable table with search, URL-backed filters, sorting, configurable columns, pagination, selection, bulk actions, a primary Manage action, and an overflow action menu. Adapt this information architecture for the audio review queue and, on wide screens, an optional compact video-list presentation. Deep links must retain the active virtual view and filters. [PeerTube My Videos](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/%2Bmy-library/my-videos/my-videos.component.html)

PeerTube separates quick filters from advanced filters, summarizes active filters while the advanced panel is collapsed, exposes `aria-expanded`, and stacks the summary on small screens. Media Manager's named virtual views should remain the always-visible quick navigation; any future search/sort controls should be secondary and collapsible instead of competing with those views. [PeerTube filter header](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/shared/shared-video-miniature/video-filters-header.component.html), [responsive filter styles](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/shared/shared-video-miniature/video-filters-header.component.scss)

PeerTube's reusable video list supports grid or row presentation, semantic heading levels, date grouping, infinite loading with a real Load more link as fallback, and a centered small-screen header. The useful pattern is progressive enhancement: Media Manager can use incremental loading without making pagination, headings, or navigation dependent on scrolling gestures. [PeerTube video list component](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/shared/shared-video-miniature/videos-list.component.ts), [video list template](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/shared/shared-video-miniature/videos-list.component.html)

PeerTube represents upload failure beside progress and provides an explicit Retry action. Media Manager should preserve the failed designer revision locally in the upload panel until retry or dismissal, rather than collapsing the operation into a transient toast. [PeerTube upload progress](https://github.com/Chocobozzz/PeerTube/blob/9cf034c43a099abe48696725061c375b2f7fd06a/client/src/app/shared/shared-upload/upload-progress.component.html)

### 3. PhotoPrism: responsive shell, card density, and semantic tokens

PhotoPrism switches from a navigation drawer to a compact fixed toolbar on small screens and offers a collapsible rail on larger screens. Media Manager has few top-level destinations, so use the simpler version: desktop rail/sidebar for Video and Audio Review with virtual views nested beneath them; mobile top bar plus a drawer or compact bottom navigation. Do not duplicate the same destination simultaneously in tabs and sidebar. [PhotoPrism responsive navigation](https://github.com/photoprism/photoprism/blob/5bd0cb57f6faa504fc176bfee2ba2c783e2209a6/frontend/src/component/navigation.vue)

PhotoPrism's card view uses responsive columns, lazy placeholders, a dominant preview, minimal overlaid facts such as video duration, explicit selection, empty-state guidance, and optional metadata below the preview. Adapt the structure but reduce density: title, review/publication state, active-variant indicator, and one next action are enough on the canonical card. Linked variants belong in the detail surface, not as separate cards. [PhotoPrism card view](https://github.com/photoprism/photoprism/blob/5bd0cb57f6faa504fc176bfee2ba2c783e2209a6/frontend/src/component/photo/view/cards.vue)

PhotoPrism defines colors by semantic role—background, surface, card, selected, highlight, error, warning, success, remove, restore—plus hover, focus, border, and disabled opacity. Use the same design-system method, not the same values. This prevents scattered one-off colors and keeps state meaning consistent between cards, uploads, review rows, and dialogs. [PhotoPrism theme tokens](https://github.com/photoprism/photoprism/blob/5bd0cb57f6faa504fc176bfee2ba2c783e2209a6/frontend/src/options/themes.js)

## Proposed Media Manager design-system contract

### Foundations

- Semantic color roles: canvas, surface, raised surface, text, muted text, border, accent, focus, info, success, warning, danger, destructive, restore.
- A small spacing scale used everywhere; one compact and one comfortable density mode.
- Consistent radii for controls, cards, and dialogs; elevation only for overlays, sticky bars, and upload status.
- Typography roles rather than page-specific sizes: page title, section title, card title, body, metadata, label.
- Motion limited to state continuity (selection, panel expansion, upload progress), with reduced-motion support.

### Reusable components

- `AppShell`, `PrimaryNav`, `VirtualViewNav`, `PageHeader`
- `MediaCard`, `MediaPreview`, `StateBadge`, `VariantMenu`, `RevisionHistory`
- `ReviewRow`, `TitleEditor`, `ApprovalAction`
- `SelectionBar`, `ActionMenu`, `ConfirmDialog`
- `UploadQueue`, `UploadItem`, `ProgressIndicator`
- `EmptyState`, `ErrorState`, `SkeletonCard`, `ToastRegion`

Component APIs should consume domain objects and capabilities, not tag strings or folder names. For example, the designer action receives whether a pipeline final accepts a new revision; it does not infer that from a `designer` tag.

## Accessibility and responsive acceptance rules

- Implement virtual-view navigation as links when each view has its own URL. Use the ARIA tabs pattern only if the controls switch panels without navigation; if tabs are used, provide `tablist`, `tab`, `tabpanel`, `aria-selected`, `aria-controls`, and arrow-key behavior. [WAI-ARIA tabs pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)
- Prefer a simple list of focusable card links initially. Only declare an ARIA grid if roving focus and the full arrow-key interaction model are implemented; WAI notes that a grid is a composite widget requiring managed focus. [WAI-ARIA grid pattern](https://www.w3.org/WAI/ARIA/apg/patterns/grid/)
- Dialogs must move focus inside, contain the tab sequence, close with Escape, and return focus logically. Destructive confirmation must name the affected item or count and clearly distinguish trash from permanent deletion. [WAI-ARIA modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
- Provide at least a 24 by 24 CSS-pixel target or sufficient spacing under WCAG 2.2, while aiming for 44 by 44 pixels for frequent mobile actions. [WCAG 2.2 target size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- Announce asynchronous upload, approval, retry, and deletion outcomes through a status region without moving focus. [WCAG status messages guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)
- Never make hover the only way to discover an action. Preserve visible focus, logical headings, text labels or accessible names for icons, and native controls.
- Test at narrow phone, wide phone, tablet, laptop, and large desktop widths; also test keyboard-only use, coarse pointer, 200% zoom, RTL text, long Arabic titles, reduced motion, empty queues, slow uploads, and failed uploads.

## What not to carry forward

- Folder or platform-tag navigation (`FB`, `TT`, `YT`, `all`, `designer`, `no-overlay`, `pending`). Virtual views come from explicit state.
- Separate list cards for linked variants or designer revisions.
- Destructive actions mixed beside the primary next-step action.
- Hover-only menus, unlabeled icon buttons, fixed card widths, transient-only upload feedback, or state communicated solely by color.
- A framework migration justified only by appearance. The design-system boundary and component architecture provide the durable improvement; a stack migration adds risk without improving the domain model by itself.

## Suggested implementation order

1. Freeze the route/view and card-domain contracts; remove tag/folder assumptions from frontend view models.
2. Add semantic tokens and accessible primitives without changing behavior.
3. Build the responsive shell and virtual-view navigation.
4. Replace video cards with the canonical card/detail/revision pattern.
5. Replace audio review with compact review rows.
6. Add the persistent upload queue and complete loading, empty, error, retry, and confirmation states.
7. Run responsive, keyboard, screen-reader, and regression checks before replacing the current entry point.

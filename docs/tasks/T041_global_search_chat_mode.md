# T041: Global Search Chat Mode Switch

## Status
Done

## Goal
Make web chat use all embedded YouTube videos by default while preserving explicit channel/account scoping.

## In scope
- Add channel/account scope to web chat messages.
- Keep the empty/default web chat scope as all embedded videos.
- Preserve channel/persona chat's explicit channel scope.

## Out of scope
- Persona prompt refresh fixes.
- Silent default changes to chat retrieval scope.

## Guardrails
- Default web chat retrieval should not filter by `chat_enabled`.
- Channel/account scope must pass `channel_id` into retrieval.
- Existing `/api/search` behavior remains unchanged.

## Validation
- Regression tests prove web chat passes channel scope and default chat retrieval searches all embedded videos.

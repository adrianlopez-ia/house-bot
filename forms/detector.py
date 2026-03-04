"""Pure functions for detecting form fields on a Playwright page.

No external dependencies beyond Playwright -- no DB, no AI, no config.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

_DETECT_FIELDS_JS = """\
(() => {
    const results = [];
    for (const form of document.querySelectorAll('form')) {
        for (const el of form.querySelectorAll('input, textarea, select')) {
            if (el.type === 'hidden' || el.type === 'submit') continue;
            results.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || 'text',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                label: findLabel(el),
                required: el.required,
                selector: buildSelector(el),
            });
        }
    }
    return results;

    function findLabel(el) {
        if (el.id) {
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) return lbl.textContent.trim();
        }
        const parent = el.closest('label');
        if (parent) return parent.textContent.trim().substring(0, 100);
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === 'LABEL') return prev.textContent.trim();
        return '';
    }

    function buildSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.name) return '[name="' + el.name + '"]';
        return '';
    }
})()
"""

_FIND_SUBMIT_JS = """\
(() => {
    const candidates = [
        ...document.querySelectorAll(
            'button[type="submit"], input[type="submit"], '
            + 'button:not([type]), [role="button"]'
        )
    ];
    const keywords = [
        'enviar', 'send', 'submit', 'solicitar', 'inscribir',
        'registrar', 'contactar', 'aceptar'
    ];
    for (const btn of candidates) {
        const text = (btn.textContent || btn.value || '').toLowerCase().trim();
        for (const kw of keywords) {
            if (text.includes(kw)) {
                if (btn.id) return '#' + btn.id;
                if (btn.name) return '[name="' + btn.name + '"]';
                return 'button:has-text("' + btn.textContent.trim() + '")';
            }
        }
    }
    const first = document.querySelector('button[type="submit"], input[type="submit"]');
    if (first) {
        if (first.id) return '#' + first.id;
        return 'button[type="submit"], input[type="submit"]';
    }
    return null;
})()
"""


async def detect_fields(page: Page) -> list[dict[str, Any]]:
    """Return a list of field descriptors found inside ``<form>`` elements."""
    fields: list[dict[str, Any]] = await page.evaluate(_DETECT_FIELDS_JS)
    logger.info("Detected %d form fields", len(fields))
    return fields


async def find_submit_button(page: Page) -> Optional[str]:
    """Return the CSS selector of the most likely submit button, or *None*."""
    return await page.evaluate(_FIND_SUBMIT_JS)

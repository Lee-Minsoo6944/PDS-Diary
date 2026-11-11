// 과제 1 소개 페이지의 탭 동작 <script> 를 그대로 옮긴 파일 (서버 CSP가 인라인 스크립트를 막아서 분리)
(function () {
    const tabButtons = Array.from(document.querySelectorAll('.tab-button'));
    const panels = Array.from(document.querySelectorAll('.tab-panel'));
    const timelineItems = Array.from(document.querySelectorAll('.timeline-item'));

    function activateTab(index, focusTab) {
        tabButtons.forEach((btn, i) => {
            const selected = i === index;
            btn.setAttribute('aria-selected', selected ? 'true' : 'false');
            btn.tabIndex = selected ? 0 : -1;
        });
        panels.forEach((panel, i) => {
            if (i === index) {
                panel.removeAttribute('hidden');
            } else {
                panel.setAttribute('hidden', '');
            }
        });
        timelineItems.forEach((item, i) => {
            item.classList.toggle('active', i === index);
        });
        if (focusTab) {
            tabButtons[index].focus();
        }
    }

    // 클릭
    tabButtons.forEach((btn, i) => {
        btn.addEventListener('click', () => activateTab(i, false));
    });

    // 키보드: 좌우 화살표 / Home / End 지원
    tabButtons.forEach((btn, i) => {
        btn.addEventListener('keydown', (e) => {
            let next = null;
            if (e.key === 'ArrowRight') next = (i + 1) % tabButtons.length;
            else if (e.key === 'ArrowLeft') next = (i - 1 + tabButtons.length) % tabButtons.length;
            else if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = tabButtons.length - 1;
            if (next !== null) {
                e.preventDefault();
                activateTab(next, true);
            }
        });
    });

    // 타임라인 항목 클릭 시 해당 탭으로 이동
    timelineItems.forEach((item) => {
        item.setAttribute('tabindex', '0');
        item.setAttribute('role', 'button');
        item.addEventListener('click', () => {
            const targetId = item.getAttribute('data-target');
            const index = tabButtons.findIndex((btn) => btn.id === targetId);
            if (index >= 0) activateTab(index, true);
        });
        item.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const targetId = item.getAttribute('data-target');
                const index = tabButtons.findIndex((btn) => btn.id === targetId);
                if (index >= 0) activateTab(index, true);
            }
        });
    });
})();

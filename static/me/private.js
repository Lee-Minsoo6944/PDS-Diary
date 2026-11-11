// 과제 8: 비공개 영역 — 패스키 등록·로그인·로그아웃과 비공개 자료 조회.
// 서버 쪽 짝: intro.py (/api/me/*), 서명 검사: passkey.py
// 비공개 내용은 이 파일에도 HTML 에도 없고, 로그인한 뒤 /api/me/items 응답으로만 받습니다.
//
// 같은 파일을 두 곳에서 씁니다.
// - https://alstn.pythonanywhere.com/me/  : API 가 같은 주소 → HttpOnly 쿠키 세션
// - https://lee-minsoo6944.github.io/About-me/ : <script data-api="https://alstn.pythonanywhere.com/api/me/">
//   API 가 다른 주소 → 서버가 본문으로 준 세션 토큰을 sessionStorage(탭을 닫으면 지워짐)에 두고 Authorization 머리글로 보냄
(function () {
    'use strict';

    const script = document.currentScript;
    const API = (script && script.dataset.api) || '/api/me/';
    const CROSS = new URL(API, location.href).origin !== location.origin;
    const TOKEN_KEY = 'me_session_token';
    const store = {
        get() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } },
        set(v) { try { if (v) sessionStorage.setItem(TOKEN_KEY, v); else sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* 저장 불가 */ } }
    };

    const $ = (id) => document.getElementById(id);
    const status = $('pz-status');

    // ---------------------------------------------------------------- 도구
    function say(msg, isError) {
        status.textContent = msg || '';
        status.classList.toggle('error', !!isError);
    }

    function b64ToBuf(s) {
        s = s.replace(/-/g, '+').replace(/_/g, '/');
        while (s.length % 4) s += '=';
        const bin = atob(s);
        const out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out.buffer;
    }

    function bufToB64(buf) {
        const bytes = new Uint8Array(buf);
        let bin = '';
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }

    function kst(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleString('ko-KR', {
            timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        });
    }

    async function api(method, path, body) {
        const opt = { method: method, headers: {}, credentials: CROSS ? 'omit' : 'same-origin' };
        if (method !== 'GET') opt.headers['X-PDS'] = '1'; // 서버의 CSRF 확인용 머리글
        if (CROSS && store.get()) opt.headers['Authorization'] = 'Bearer ' + store.get();
        if (body !== undefined) {
            opt.headers['Content-Type'] = 'application/json';
            opt.body = JSON.stringify(body);
        }
        const r = await fetch(API + path, opt);
        let data = null;
        try { data = await r.json(); } catch (e) { /* 본문 없음 */ }
        if (data && data.token) store.set(data.token); // 다른 주소에서 쓸 때만 서버가 토큰을 줌
        if (!r.ok) {
            if (r.status === 401 && CROSS) store.set(null);
            const err = new Error((data && data.error) || ('HTTP ' + r.status));
            err.status = r.status;
            throw err;
        }
        return data;
    }

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text; // innerHTML 을 쓰지 않음(자료에 태그가 있어도 글자로만)
        return e;
    }

    function busy(form, on) {
        form.querySelectorAll('button').forEach((b) => { b.disabled = on; });
    }

    // ---------------------------------------------------------------- 서버 옵션 ↔ 브라우저 WebAuthn 형식
    function toCreateOptions(pk) {
        return Object.assign({}, pk, {
            challenge: b64ToBuf(pk.challenge),
            user: Object.assign({}, pk.user, { id: b64ToBuf(pk.user.id) }),
            excludeCredentials: pk.excludeCredentials.map((c) => Object.assign({}, c, { id: b64ToBuf(c.id) }))
        });
    }

    function toGetOptions(pk) {
        return Object.assign({}, pk, {
            challenge: b64ToBuf(pk.challenge),
            allowCredentials: pk.allowCredentials.map((c) => Object.assign({}, c, { id: b64ToBuf(c.id) }))
        });
    }

    // 서버로 보내는 것: 자격 증명 ID, clientDataJSON, attestationObject(공개키가 들어 있음). 개인키는 없음.
    function registrationJSON(cred) {
        const r = cred.response;
        return {
            id: cred.id, rawId: bufToB64(cred.rawId), type: cred.type,
            response: {
                clientDataJSON: bufToB64(r.clientDataJSON),
                attestationObject: bufToB64(r.attestationObject),
                transports: typeof r.getTransports === 'function' ? r.getTransports() : []
            }
        };
    }

    // 서버로 보내는 것: 서명, 서명한 데이터(authenticatorData + clientDataJSON).
    function assertionJSON(cred) {
        const r = cred.response;
        return {
            id: cred.id, rawId: bufToB64(cred.rawId), type: cred.type,
            response: {
                clientDataJSON: bufToB64(r.clientDataJSON),
                authenticatorData: bufToB64(r.authenticatorData),
                signature: bufToB64(r.signature),
                userHandle: r.userHandle ? bufToB64(r.userHandle) : null
            }
        };
    }

    function explain(e, what) {
        if (e && e.name === 'NotAllowedError') {
            return what + ' 창이 닫혀 취소되었습니다(직접 닫았거나 시간이 지났습니다). 서버에는 아무것도 저장되지 않았습니다.';
        }
        if (e && e.name === 'InvalidStateError') {
            return '이 인증기(기기·비밀번호 관리자)에는 이 계정의 패스키가 이미 있습니다. 휴대폰·보안 키·다른 비밀번호 관리자처럼 다른 곳을 고르세요.';
        }
        if (e && e.name === 'SecurityError') {
            return '이 주소에서는 패스키를 쓸 수 없습니다. https 주소(또는 개발 중에는 http://localhost)로 여세요.';
        }
        return what + ' 실패: ' + ((e && e.message) || e);
    }

    // ---------------------------------------------------------------- 등록 (새 계정 / 패스키 추가 공용)
    async function register(body) {
        const opts = await api('POST', 'register/options', body);
        let cred;
        try {
            cred = await navigator.credentials.create({ publicKey: toCreateOptions(opts.publicKey) });
        } catch (e) {
            // 취소: 보관 중인 챌린지까지 지워 서버에 남는 것이 없게 함
            api('POST', 'cancel', { challenge: opts.publicKey.challenge }).catch(() => {});
            throw e;
        }
        return api('POST', 'register/verify', { credential: registrationJSON(cred) });
    }

    // ---------------------------------------------------------------- 화면
    async function showPrivate() {
        let session;
        try {
            session = await api('GET', 'session');
        } catch (e) {
            if (e.status === 401) { showLoggedOut(); return; }
            say('비공개 영역 상태를 확인하지 못했습니다: ' + e.message, true);
            return;
        }
        $('pz-out').hidden = true;
        $('pz-in').hidden = false;
        $('pz-who').textContent = session.account.username;
        await Promise.all([loadItems(), loadPasskeys()]);
    }

    function showLoggedOut() {
        if (CROSS) store.set(null);
        $('pz-in').hidden = true;
        $('pz-out').hidden = false;
        $('item-list').replaceChildren();
        $('pk-list').replaceChildren();
    }

    async function loadItems() {
        const data = await api('GET', 'items');
        const list = $('item-list');
        list.replaceChildren();
        $('item-count').textContent = data.items.length + '개';
        data.items.forEach((it) => {
            const li = el('li');
            li.append(el('span', 'item-cat', it.category_label), el('span', 'item-title', it.title),
                el('span', 'item-body', it.body));
            const foot = el('div', 'item-foot');
            foot.append(el('span', '', kst(it.created_at)));
            const del = el('button', 'pz-btn pz-danger', '지우기');
            del.type = 'button';
            del.addEventListener('click', async () => {
                if (!confirm('"' + it.title + '" 자료를 지울까요?')) return;
                try {
                    await api('DELETE', 'items/' + it.id);
                    say('자료를 지웠습니다.');
                    loadItems();
                } catch (e) { handleError(e, '자료 지우기'); }
            });
            foot.append(del);
            li.append(foot);
            list.append(li);
        });
    }

    function keyText(k) {
        if (k.alg === 'ES256') return 'ES256 · P-256\nx=' + k.x.slice(0, 16) + '…\ny=' + k.y.slice(0, 16) + '…';
        if (k.alg === 'RS256') return 'RS256 · RSA ' + k.n_bits + '비트, e=' + k.e;
        return k.alg;
    }

    async function loadPasskeys() {
        const data = await api('GET', 'passkeys');
        const body = $('pk-list');
        body.replaceChildren();
        $('pk-count').textContent = data.passkeys.length + '개';
        data.passkeys.forEach((p) => {
            const tr = el('tr');
            const key = el('td', 'pk-key', keyText(p.public_key));
            key.title = 'credential ID: ' + p.credential_id + '\nAAGUID: ' + p.aaguid;
            const delTd = el('td');
            const del = el('button', 'pz-btn pz-danger', '삭제');
            del.type = 'button';
            del.addEventListener('click', () => deletePasskey(p));
            delTd.append(del);
            tr.append(el('td', '', p.name), el('td', '', kst(p.created_at)), el('td', '', kst(p.last_used_at)),
                el('td', '', p.storage), key, delTd);
            body.append(tr);
        });
        const warn = $('pk-warning');
        if (data.passkeys.length <= 1) {
            warn.hidden = false;
            warn.textContent = '⚠ 패스키가 하나뿐입니다. 이 패스키가 있는 기기·비밀번호 관리자를 쓸 수 없게 되면 다시 들어올 방법이 없습니다 '
                + '(비밀번호·이메일 복구가 없습니다). 아래에서 다른 곳에 하나 더 만들어 두세요. 마지막 남은 패스키는 지울 수 없습니다.';
        } else {
            warn.hidden = true;
        }
    }

    async function deletePasskey(p) {
        if (!confirm('패스키 "' + p.name + '" — 지울까요?\n지운 뒤에는 이 패스키로 들어올 수 없습니다.')) return;
        try {
            const r = await api('DELETE', 'passkeys/' + p.id);
            say('패스키 "' + p.name + '" 삭제 완료. 남은 패스키 ' + r.left + '개.');
            loadPasskeys();
        } catch (e) { handleError(e, '패스키 삭제'); }
    }

    function handleError(e, what) {
        if (e.status === 401) {
            showLoggedOut();
            say('로그인이 끝났습니다. 다시 패스키로 들어가 주세요.', true);
            return;
        }
        say(what + ' 실패: ' + e.message, true);
    }

    // ---------------------------------------------------------------- 버튼
    $('login-form').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const form = ev.currentTarget;
        busy(form, true);
        say('기기에서 패스키를 확인해 주세요…');
        let opts;
        try {
            opts = await api('POST', 'login/options', { username: $('login-username').value.trim() });
            const cred = await navigator.credentials.get({ publicKey: toGetOptions(opts.publicKey) });
            const r = await api('POST', 'login/verify', { credential: assertionJSON(cred) });
            say('들어왔습니다. 사용한 패스키: ' + r.passkey);
            await showPrivate();
        } catch (e) {
            if (opts && e.name === 'NotAllowedError') api('POST', 'cancel', { challenge: opts.publicKey.challenge }).catch(() => {});
            say(explain(e, '로그인'), true);
        } finally { busy(form, false); }
    });

    $('signup-form').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const form = ev.currentTarget;
        busy(form, true);
        say('기기에서 새 패스키를 만들어 주세요…');
        try {
            const r = await register({ username: $('signup-username').value.trim(), passkey_name: $('signup-pkname').value.trim() });
            say('가입했습니다. 패스키 "' + r.passkey.name + '" 등록 완료 — 서버에는 공개키만 저장되었습니다.');
            form.reset();
            await showPrivate();
        } catch (e) {
            say(explain(e, '등록'), true);
        } finally { busy(form, false); }
    });

    $('addpk-form').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const form = ev.currentTarget;
        busy(form, true);
        say('새 패스키를 만들 기기·보안 키를 골라 주세요…');
        try {
            const r = await register({ passkey_name: $('addpk-name').value.trim() });
            say('패스키 "' + r.passkey.name + '" 추가 완료 (' + r.passkey.storage + ').');
            form.reset();
            await loadPasskeys();
        } catch (e) {
            if (e.status === 401) { handleError(e, '패스키 추가'); return; }
            say(explain(e, '패스키 추가'), true);
        } finally { busy(form, false); }
    });

    $('item-form').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const form = ev.currentTarget;
        busy(form, true);
        try {
            await api('POST', 'items', {
                category: $('item-category').value, title: $('item-title').value, body: $('item-body').value
            });
            form.reset();
            say('자료를 추가했습니다.');
            await loadItems();
        } catch (e) { handleError(e, '자료 추가'); } finally { busy(form, false); }
    });

    $('logout-btn').addEventListener('click', async () => {
        try { await api('POST', 'logout'); } catch (e) { /* 이미 끝난 세션이어도 화면은 닫음 */ }
        showLoggedOut();
        say('로그아웃했습니다. 서버에서도 세션을 지웠습니다.');
    });

    // ---------------------------------------------------------------- 시작
    if (!window.PublicKeyCredential || !navigator.credentials) {
        say('이 브라우저는 패스키를 지원하지 않습니다. 최신 Chrome·Edge·Safari·Firefox에서 열어 주세요.', true);
        document.querySelectorAll('#pz-out button').forEach((b) => { b.disabled = true; });
    } else if (!CROSS && location.hostname === '127.0.0.1') {
        say('패스키는 127.0.0.1 주소에서 쓸 수 없습니다. http://localhost:' + location.port + '/me/ 로 열어 주세요.', true);
    }
    if (CROSS && !store.get()) showLoggedOut(); else showPrivate();
})();

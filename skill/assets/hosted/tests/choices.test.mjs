import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createApp, summary } from '../lambda.mjs';

const OWNER = 'owner-secret';
const meta = { sections: [{ key: 'look', title: 'Look', groups: [{ key: 'colour', title: 'Colour', mode: 'one', names: { A: 'Ocean blue', B: 'Forest' } }] }] };
const config = (open = false) => ({ title: 'Pricing page', url: 'https://choices.hammantlabs.com/p-x/', open, ownerName: 'Jon',
  ownerHash: createHash('sha256').update(OWNER).digest('hex'), meta });

function memoryStore() {
  const m = new Map();
  return {
    m,
    async get(pk, sk) { return m.get(pk + '|' + sk) || null; },
    async put(pk, sk, data) { m.set(pk + '|' + sk, { ...data, pk, sk }); },
    async query(pk) { return [...m.values()].filter((i) => i.pk === pk); },
  };
}

function setup(open = false) {
  let t = 1_000_000;
  const alerts = [];
  const store = memoryStore();
  const app = createApp({ store, alert: async (m) => alerts.push(m), now: () => t, config: config(open) });
  const call = async (method, path, { token, body, ip } = {}) => {
    const r = await app({ rawPath: path, requestContext: { http: { method, sourceIp: ip || '1.2.3.4' } },
      headers: token ? { 'x-hl-token': token } : {}, body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: r.statusCode, json: JSON.parse(r.body) };
  };
  return { call, alerts, store, tick: (ms) => { t += ms; } };
}
const vote = (pick, note = '') => ({ sections: { look: { picks: { colour: pick }, note } } });

test('owner invites people and each gets a working personal link', async () => {
  const { call } = setup();
  const r = await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna', '  Ben  Smith '] } });
  assert.equal(r.status, 200);
  assert.deepEqual(r.json.invited.map((v) => v.name), ['Anna', 'Ben Smith']);
  const me = await call('GET', '/api/me', { token: r.json.invited[0].token });
  assert.equal(me.json.name, 'Anna');
  assert.equal(me.json.owner, false);
});

test('only the owner can invite, close or export', async () => {
  const { call } = setup();
  const [anna] = (await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna'] } })).json.invited;
  for (const [m, p, b] of [['POST', '/api/invite', { names: ['X'] }], ['POST', '/api/state', { closed: true }], ['GET', '/api/export']]) {
    assert.equal((await call(m, p, { token: anna.token, body: b })).status, 403, p);
    assert.equal((await call(m, p, { body: b })).status, 403, p + ' without token');
  }
});

test('opening alerts once per person, never for the owner', async () => {
  const { call, alerts } = setup();
  const [anna] = (await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna'] } })).json.invited;
  await call('GET', '/api/me', { token: anna.token });
  await call('GET', '/api/me', { token: anna.token });
  await call('GET', '/api/me', { token: OWNER });
  assert.equal(alerts.length, 1);
  assert.match(alerts[0], /Anna opened “Pricing page”/);
});

test('first vote alerts with readable picks; changes alert at most every 30 minutes', async () => {
  const { call, alerts, tick } = setup();
  const [anna, ben] = (await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna', 'Ben'] } })).json.invited;
  await call('PUT', '/api/votes', { token: anna.token, body: vote('A', 'love it') });
  assert.match(alerts.at(-1), /Anna voted on “Pricing page”: Colour → Ocean blue; note: “love it”/);
  await call('PUT', '/api/votes', { token: anna.token, body: vote('B') });
  assert.equal(alerts.length, 1, 'a quick change does not alert');
  tick(31 * 60 * 1000);
  await call('PUT', '/api/votes', { token: anna.token, body: vote('B') });
  assert.match(alerts.at(-1), /Anna changed their vote.*Forest/);
  await call('PUT', '/api/votes', { token: ben.token, body: vote('A') });
  assert.match(alerts.at(-1), /Everyone invited has voted on “Pricing page” \(2\/2\)/);
});

test('everyone can read the tallies; only link holders vote', async () => {
  const { call } = setup();
  const [anna] = (await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna'] } })).json.invited;
  await call('PUT', '/api/votes', { token: anna.token, body: vote('A') });
  const r = await call('GET', '/api/votes');
  assert.equal(r.status, 200);
  assert.deepEqual(r.json.votes, [{ id: anna.id, sections: vote('A').sections }]);
  assert.equal(r.json.names[anna.id], 'Anna');
  assert.equal((await call('PUT', '/api/votes', { body: vote('B') })).status, 401);
  assert.equal((await call('PUT', '/api/votes', { token: 'made-up', body: vote('B') })).status, 401);
});

test('closing voting stops changes and shows in the state', async () => {
  const { call } = setup();
  const [anna] = (await call('POST', '/api/invite', { token: OWNER, body: { names: ['Anna'] } })).json.invited;
  await call('POST', '/api/state', { token: OWNER, body: { closed: true } });
  assert.equal((await call('PUT', '/api/votes', { token: anna.token, body: vote('A') })).status, 409);
  assert.equal((await call('GET', '/api/votes')).json.closed, true);
});

test('open pages let anyone join by name, with a per-IP limit', async () => {
  const { call, alerts } = setup(true);
  const j = await call('POST', '/api/join', { body: { name: 'Cara' } });
  assert.equal(j.status, 200);
  assert.ok(j.json.token);
  assert.match(alerts.at(-1), /Cara joined/);
  assert.equal((await call('GET', '/api/me', { token: j.json.token })).json.name, 'Cara');
  for (let i = 0; i < 10; i++) await call('POST', '/api/join', { body: { name: 'x' + i }, ip: '9.9.9.9' });
  assert.equal((await call('POST', '/api/join', { body: { name: 'y' }, ip: '9.9.9.9' })).status, 429);
  assert.equal((await setup(false).call('POST', '/api/join', { body: { name: 'z' } })).status, 403, 'invite-only refuses joins');
});

test('bad requests are refused cleanly', async () => {
  const { call } = setup();
  assert.equal((await call('GET', '/api/nope')).status, 404);
  assert.equal((await call('PUT', '/api/votes', { token: OWNER, body: { sections: [] } })).status, 400);
  assert.equal((await call('POST', '/api/invite', { token: OWNER, body: { names: ['x'.repeat(30000)] } })).status, 413);
});

test('summary turns picks into option names', () => {
  assert.equal(summary(vote('B').sections, meta), 'Colour → Forest');
  assert.equal(summary({}, meta), 'no picks yet');
});

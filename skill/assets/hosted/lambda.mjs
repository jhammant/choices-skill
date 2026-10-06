// Server for a hosted /choices page on choices.hammantlabs.com/<slug>/ (deployed by hlsite as its own Lambda).
// Voters hold personal links (?v=<token>); only token hashes are stored. Votes, who-has-opened and the closed flag
// live in the page's own DynamoDB table. Opening, voting and "everyone has voted" alert Jon via the platform topic.
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';

const loadConfig = () => JSON.parse(readFileSync(new URL('./choices-config.json', import.meta.url), 'utf8'));
const CHANGE_ALERT_GAP = 30 * 60 * 1000;
const MAX_BODY = 20000;
const hash = (t) => createHash('sha256').update(String(t)).digest('hex');
const fail = (status, error) => { throw Object.assign(new Error(error), { status }); };
const cleanName = (n) => (typeof n === 'string' ? n.replace(/\s+/g, ' ').trim().slice(0, 40) : '');

export function summary(sections, meta) {
  const parts = [];
  for (const s of meta.sections || []) {
    const sec = sections?.[s.key];
    if (!sec) continue;
    for (const g of s.groups) {
      const raw = sec.picks?.[g.key];
      const picks = Array.isArray(raw) ? raw : raw ? [raw] : [];
      if (picks.length) parts.push(`${g.title} → ${picks.map((v) => g.names?.[v] || v).join(g.mode === 'rank' ? ' > ' : ', ')}`);
    }
    if (sec.note) parts.push(`note: “${String(sec.note).slice(0, 140)}”`);
  }
  return parts.join('; ').slice(0, 900) || 'no picks yet';
}

export function createApp({ store, alert, now = () => Date.now(), config }) {
  const title = `“${config.title}”`;

  async function who(event) {
    const token = event.headers?.['x-hl-token'];
    if (!token) return null;
    const h = hash(token);
    if (h === config.ownerHash) return { id: 'owner', name: config.ownerName || 'Owner', owner: true };
    const v = await store.get('TOKEN', h);
    return v ? { id: v.id, name: v.name, owner: false } : null;
  }

  async function voters() {
    return (await store.query('VOTER')).map((v) => ({ id: v.sk, name: v.name }));
  }

  async function addVoter(name) {
    const id = randomUUID().slice(0, 8);
    const token = randomBytes(18).toString('base64url');
    await store.put('VOTER', id, { name, created: now() });
    await store.put('TOKEN', hash(token), { id, name });
    return { id, name, token };
  }

  const routes = {
    'GET /api/me': async (event) => {
      const me = await who(event);
      if (!me) fail(401, config.open ? 'join first' : 'this link is view-only');
      if (!me.owner && !(await store.get('SEEN', me.id))) {
        await store.put('SEEN', me.id, { at: now() });
        await alert(`👀 ${me.name} opened ${title}\n${config.url}`);
      }
      return { id: me.id, name: me.name, owner: me.owner, open: !!config.open };
    },
    'POST /api/join': async (event, body) => {
      if (!config.open) fail(403, 'this page is invite-only');
      const name = cleanName(body.name);
      if (!name) fail(400, 'type your name');
      const ip = event.requestContext?.http?.sourceIp || 'unknown';
      const bucket = `${hash(ip).slice(0, 16)}#${Math.floor(now() / 3600000)}`;
      const seen = (await store.get('RATE', bucket))?.n || 0;
      if (seen >= 10) fail(429, 'too many joins from here; try later');
      await store.put('RATE', bucket, { n: seen + 1, ttl: Math.floor(now() / 1000) + 7200 });
      if ((await voters()).length >= 200) fail(403, 'this page is full');
      const v = await addVoter(name);
      await store.put('SEEN', v.id, { at: now() });
      await alert(`🙋 ${name} joined ${title}\n${config.url}`);
      return v;
    },
    'GET /api/votes': async () => {
      const [votes, list, state] = await Promise.all([store.query('VOTE'), voters(), store.get('STATE', 'state')]);
      const names = Object.fromEntries(list.map((v) => [v.id, v.name]));
      names.owner = config.ownerName || 'Owner';
      return { votes: votes.map((v) => ({ id: v.sk, sections: v.sections })), names, closed: !!state?.closed };
    },
    'PUT /api/votes': async (event, body) => {
      const me = await who(event);
      if (!me) fail(401, 'you need your personal link to vote');
      if ((await store.get('STATE', 'state'))?.closed) fail(409, 'voting is closed');
      if (!body.sections || typeof body.sections !== 'object' || Array.isArray(body.sections)) fail(400, 'no sections');
      const prev = await store.get('VOTE', me.id);
      await store.put('VOTE', me.id, { sections: body.sections, at: now(), name: me.name });
      if (me.owner) return { ok: true };
      const last = await store.get('ALERT', `vote#${me.id}`);
      if (!prev) {
        await alert(`🗳️ ${me.name} voted on ${title}: ${summary(body.sections, config.meta)}\n${config.url}`);
        await store.put('ALERT', `vote#${me.id}`, { at: now() });
      } else if (!last || now() - last.at > CHANGE_ALERT_GAP) {
        await alert(`✏️ ${me.name} changed their vote on ${title}: ${summary(body.sections, config.meta)}`);
        await store.put('ALERT', `vote#${me.id}`, { at: now() });
      }
      if (!config.open && !prev && !(await store.get('ALERT', 'all'))) {
        const [list, votes] = await Promise.all([voters(), store.query('VOTE')]);
        const voted = new Set(votes.map((v) => v.sk));
        if (list.length && list.every((v) => voted.has(v.id))) {
          await store.put('ALERT', 'all', { at: now() });
          await alert(`✅ Everyone invited has voted on ${title} (${list.length}/${list.length}). Ask Claude to tally it.`);
        }
      }
      return { ok: true };
    },
    'POST /api/state': async (event, body) => {
      const me = await who(event);
      if (!me?.owner) fail(403, 'only the owner can open or close voting');
      await store.put('STATE', 'state', { closed: !!body.closed, at: now() });
      return { closed: !!body.closed };
    },
    'POST /api/invite': async (event, body) => {
      const me = await who(event);
      if (!me?.owner) fail(403, 'only the owner can invite');
      const names = (Array.isArray(body.names) ? body.names : []).map(cleanName).filter(Boolean).slice(0, 100);
      if (!names.length) fail(400, 'no names');
      const out = [];
      for (const n of names) out.push(await addVoter(n));
      return { invited: out };
    },
    'GET /api/export': async (event) => {
      const me = await who(event);
      if (!me?.owner) fail(403, 'only the owner can export');
      const [votes, list, seen, state] = await Promise.all([store.query('VOTE'), voters(), store.query('SEEN'), store.get('STATE', 'state')]);
      const voted = new Set(votes.map((v) => v.sk));
      const opened = new Set(seen.map((s) => s.sk));
      return {
        title: config.title, closed: !!state?.closed,
        voters: list.map((v) => ({ ...v, opened: opened.has(v.id), voted: voted.has(v.id) })),
        votes: votes.map((v) => ({ id: v.sk, name: v.name, at: v.at, sections: v.sections })),
      };
    },
  };

  return async (event) => {
    const method = event.requestContext?.http?.method || 'GET';
    const route = routes[`${method} ${event.rawPath}`];
    const headers = { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' };
    try {
      if (!route) fail(404, 'not found');
      let body = {};
      if (method !== 'GET') {
        const raw = event.isBase64Encoded ? Buffer.from(event.body || '', 'base64').toString() : event.body || '';
        if (raw.length > MAX_BODY) fail(413, 'too much');
        try { body = raw ? JSON.parse(raw) : {}; } catch { fail(400, 'bad JSON'); }
      }
      return { statusCode: 200, headers, body: JSON.stringify(await route(event, body)) };
    } catch (e) {
      const status = e.status || 500;
      if (status === 500) console.error(e);
      return { statusCode: status, headers, body: JSON.stringify({ error: status === 500 ? 'server error, try again' : e.message }) };
    }
  };
}

function dynamoStore(table) {
  let docs;
  const client = async () => {
    if (!docs) {
      const { DynamoDBClient } = await import('@aws-sdk/client-dynamodb');
      const { DynamoDBDocumentClient } = await import('@aws-sdk/lib-dynamodb');
      docs = { lib: await import('@aws-sdk/lib-dynamodb'), c: DynamoDBDocumentClient.from(new DynamoDBClient({})) };
    }
    return docs;
  };
  return {
    async get(pk, sk) {
      const { lib, c } = await client();
      return (await c.send(new lib.GetCommand({ TableName: table, Key: { pk, sk }, ConsistentRead: true }))).Item || null;
    },
    async put(pk, sk, data) {
      const { lib, c } = await client();
      await c.send(new lib.PutCommand({ TableName: table, Item: { ...data, pk, sk } }));
    },
    async query(pk) {
      const { lib, c } = await client();
      const items = [];
      let ExclusiveStartKey;
      do {
        const r = await c.send(new lib.QueryCommand({ TableName: table, KeyConditionExpression: 'pk = :pk',
          ExpressionAttributeValues: { ':pk': pk }, ExclusiveStartKey }));
        items.push(...(r.Items || []));
        ExclusiveStartKey = r.LastEvaluatedKey;
      } while (ExclusiveStartKey);
      return items;
    },
  };
}

async function snsAlert(message) {
  if (!process.env.HL_ALERTS_TOPIC) return;
  try {
    const { SNSClient, PublishCommand } = await import('@aws-sdk/client-sns');
    await new SNSClient({}).send(new PublishCommand({ TopicArn: process.env.HL_ALERTS_TOPIC, Message: message }));
  } catch (e) {
    console.error('alert failed', e); // an alert must never break voting
  }
}

let app;
export async function handler(event) {
  app ||= createApp({ store: dynamoStore(process.env.TABLE_NAME), alert: snsAlert, config: loadConfig() });
  return app(event);
}

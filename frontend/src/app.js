import m from "mithril";

const TOKEN_KEY = "bridge_strain_token";
const USER_KEY = "bridge_strain_user";

// 与后端 rules.py 同一公式，仅用于输入时的本地预览；
// 落单与判定一律以后端换算、后台工人判定为准。
function previewMicrostrain(voltage, sensitivity, ratedVoltage) {
  const u = parseFloat(voltage);
  const k = parseFloat(sensitivity);
  const ur = parseFloat(ratedVoltage);
  if (![u, k, ur].every(Number.isFinite) || k <= 0 || ur <= 0) return null;
  return (u / (ur * k)) * 1_000_000;
}

function fmtNum(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : String(value);
}

function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

function verdictClass(verdict, status) {
  if (verdict === "合格") return "tag pass";
  if (verdict === "越界") return "tag fail";
  return "tag wait";
}

function displayVerdict(row) {
  if (row.verdict) return row.verdict;
  if (row.status === "pending") return "待处理";
  if (row.status === "processing") return "处理中";
  return "—";
}

function pathLabel(path) {
  if (path === "voltage") return "电压换算";
  if (path === "direct") return "微应变直填";
  return path || "—";
}

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  view: "list",
  loginForm: { username: "surveyor", password: "surv123456" },
  convertForm: {
    span_code: "",
    voltage: "",
    microstrain: "",
    sensitivity: "2.0",
    ratedVoltage: "5.0",
  },
  rows: [],
  logs: [],
  error: "",
  msg: "",
  loading: false,
  timer: null,
};

try {
  state.user = JSON.parse(localStorage.getItem(USER_KEY) || "null");
} catch {
  state.user = null;
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

async function loadReadings() {
  if (!state.token) return;
  try {
    state.rows = await api("/api/readings");
    state.error = "";
  } catch {
    state.error = "加载列表失败，请重新登录";
  }
  m.redraw();
}

async function loadLogs() {
  if (!state.token || state.view !== "convert") return;
  try {
    state.logs = await api("/api/conversion-logs");
  } catch {
    /* 列表轮询会带动重绘，流水失败保留下次重试 */
  }
  m.redraw();
}

async function refreshAll() {
  await Promise.all([loadReadings(), loadLogs()]);
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  if (!state.token) return;
  state.timer = setInterval(refreshAll, 3000);
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  state.token = "";
  state.user = null;
  state.rows = [];
  state.logs = [];
  state.view = "list";
  if (state.timer) clearInterval(state.timer);
}

const LoginView = {
  view() {
    return m("div.wrap", [
      m("h1", "桥梁应变班交台"),
      m(
        "p.sub",
        "测量员提交跨段读数：可直填微应变，也可填原始电压由服务端按灵敏度与额定电压换算后判定。"
      ),
      m("div.card", [
        m(
          "form",
          {
            onsubmit: async (e) => {
              e.preventDefault();
              state.error = "";
              state.loading = true;
              try {
                const data = await api("/api/auth/login", {
                  method: "POST",
                  body: JSON.stringify(state.loginForm),
                });
                state.token = data.access_token;
                state.user = { username: data.username, role: data.role };
                localStorage.setItem(TOKEN_KEY, state.token);
                localStorage.setItem(USER_KEY, JSON.stringify(state.user));
                await refreshAll();
                startPolling();
              } catch {
                state.error = "用户名或密码错误";
              } finally {
                state.loading = false;
                m.redraw();
              }
            },
          },
          [
            m("div.row", [
              m("label", [
                "用户名",
                m("input", {
                  value: state.loginForm.username,
                  oninput: (e) => {
                    state.loginForm.username = e.target.value;
                  },
                }),
              ]),
              m("label", [
                "密码",
                m("input", {
                  type: "password",
                  value: state.loginForm.password,
                  oninput: (e) => {
                    state.loginForm.password = e.target.value;
                  },
                }),
              ]),
              m("button", { type: "submit", disabled: state.loading }, "登录"),
            ]),
            state.error ? m("p.err", state.error) : null,
          ]
        ),
        m(
          "p.sub",
          { style: { marginBottom: 0 } },
          "测量员 surveyor / surv123456 · 复核员 reviewer / rev123456"
        ),
      ]),
    ]);
  },
};

function topbar(isWriter) {
  return m("div.topbar", [
    m("div", [
      m("h1", "桥梁应变班交台"),
      m("p.sub", "微应变 80～220 με 为合格，否则为越界。"),
    ]),
    m("div.barright", [
      m(
        "button.secondary" + (state.view === "list" ? ".active" : ""),
        {
          type: "button",
          onclick: () => {
            state.view = "list";
            loadReadings();
          },
        },
        "班交台"
      ),
      m(
        "button.secondary" + (state.view === "convert" ? ".active" : ""),
        {
          type: "button",
          onclick: () => {
            state.view = "convert";
            refreshAll();
          },
        },
        "换算专页"
      ),
      m("span.who", `${state.user?.username}（${isWriter ? "测量员" : "复核员"}）`),
      m("button.secondary", { type: "button", onclick: logout }, "退出"),
    ]),
  ]);
}

const ListView = {
  view() {
    return m("div.card", [
      m("h2", { style: { marginTop: 0, fontSize: "1.1rem" } }, "读数列表"),
      m("table", [
        m("thead", [
          m("tr", [
            m("th", "编号"),
            m("th", "跨段"),
            m("th", "原始电压(V)"),
            m("th", "灵敏度K"),
            m("th", "额定电压(V)"),
            m("th", "微应变(με)"),
            m("th", "结论"),
            m("th", "说明"),
            m("th", "状态"),
            m("th", "提交人"),
          ]),
        ]),
        m(
          "tbody",
          state.rows.length
            ? state.rows.map((r) =>
                m("tr", { key: r.id }, [
                  m("td", r.id),
                  m("td", r.span_code),
                  m("td", fmtNum(r.raw_voltage, 4)),
                  m("td", fmtNum(r.sensitivity, 3)),
                  m("td", fmtNum(r.rated_voltage, 2)),
                  m("td", fmtNum(r.microstrain, 2)),
                  m("td", [
                    m(
                      "span",
                      { class: verdictClass(r.verdict, r.status) },
                      displayVerdict(r)
                    ),
                  ]),
                  m("td", r.reason || "—"),
                  m("td", r.status),
                  m("td", r.created_by),
                ])
              )
            : [m("tr", m("td", { colspan: 10 }, "暂无数据"))]
        ),
      ]),
    ]);
  },
};

const ConvertView = {
  oninit() {
    loadLogs();
  },
  view() {
    const isWriter = state.user?.role === "writer";
    const f = state.convertForm;
    const preview = previewMicrostrain(f.voltage, f.sensitivity, f.ratedVoltage);
    const hasVoltage = f.voltage.trim() !== "";
    const hasMicrostrain = f.microstrain.trim() !== "";

    async function submit(e) {
      e.preventDefault();
      state.error = "";
      state.msg = "";
      state.loading = true;
      const body = { span_code: f.span_code };
      if (hasVoltage) {
        body.voltage = f.voltage;
        body.sensitivity = f.sensitivity;
        body.rated_voltage = f.ratedVoltage;
      } else {
        body.microstrain = f.microstrain;
      }
      try {
        const data = await api("/api/readings", {
          method: "POST",
          body: JSON.stringify(body),
        });
        state.msg =
          (data.message || "已提交") +
          `（微应变 ${fmtNum(data.microstrain, 2)} με）`;
        state.convertForm = {
          span_code: "",
          voltage: "",
          microstrain: "",
          sensitivity: f.sensitivity,
          ratedVoltage: f.ratedVoltage,
        };
        await refreshAll();
      } catch (err) {
        // 统一展示服务端退回措辞，与直打接口的 detail 逐字一致
        state.error = err.message || "提交失败";
      } finally {
        state.loading = false;
        m.redraw();
      }
    }

    return [
      m("div.card", [
        m("h2", { style: { marginTop: 0, fontSize: "1.1rem" } }, [
          "换算参数",
          isWriter
            ? null
            : m("span.hint", "（复核员只读，参数以单据与流水记录为准）"),
        ]),
        m("div.row", [
          m("label", [
            "灵敏度系数 K",
            m("input", {
              type: "number",
              step: "0.01",
              min: "0.1",
              max: "10",
              value: f.sensitivity,
              disabled: !isWriter,
              oninput: (e) => {
                f.sensitivity = e.target.value;
              },
            }),
          ]),
          m("label", [
            "额定电压 U额（V）",
            m("input", {
              type: "number",
              step: "0.1",
              min: "0.1",
              max: "1000",
              value: f.ratedVoltage,
              disabled: !isWriter,
              oninput: (e) => {
                f.ratedVoltage = e.target.value;
              },
            }),
          ]),
          m("p.formula", "με = U ÷ (U额 × K) × 10⁶"),
        ]),
      ]),
      isWriter
        ? m("div.card", [
            m("h2", { style: { marginTop: 0, fontSize: "1.1rem" } }, "报送读数（两条路径二选一）"),
            m(
              "form",
              { onsubmit: submit },
              [
                m("div.row", [
                  m("label", [
                    "跨段编号",
                    m("input", {
                      required: true,
                      placeholder: "例如 跨中S3",
                      value: f.span_code,
                      oninput: (e) => {
                        f.span_code = e.target.value;
                      },
                    }),
                  ]),
                ]),
                m("div.paths", [
                  m("div.path", [
                    m("h3", "路径一 · 原始电压（服务端换算）"),
                    m("label", [
                      "原始电压 U（V）",
                      m("input", {
                        type: "number",
                        step: "0.0001",
                        placeholder: "例如 0.0015",
                        value: f.voltage,
                        oninput: (e) => {
                          f.voltage = e.target.value;
                        },
                      }),
                    ]),
                    m(
                      "p.preview",
                      preview !== null && hasVoltage
                        ? `换算预览：${fmtNum(preview, 2)} με（仅供参考，以服务端换算为准）`
                        : "填写原始电压后显示换算预览"
                    ),
                  ]),
                  m("div.path", [
                    m("h3", "路径二 · 直接填写微应变"),
                    m("label", [
                      "微应变（με）",
                      m("input", {
                        type: "number",
                        step: "0.1",
                        placeholder: "例如 150",
                        value: f.microstrain,
                        oninput: (e) => {
                          f.microstrain = e.target.value;
                        },
                      }),
                    ]),
                    m(
                      "p.preview",
                      hasMicrostrain
                        ? `直填 ${fmtNum(f.microstrain, 2)} με，按合格带 80～220 με 判定`
                        : "直接填写微应变时不经换算"
                    ),
                  ]),
                ]),
                m("div.row", [
                  m(
                    "button",
                    { type: "submit", disabled: state.loading || (!hasVoltage && !hasMicrostrain) },
                    "提交报送"
                  ),
                  hasVoltage && hasMicrostrain
                    ? m("span.hint", "两条路径只能填写其中一条")
                    : null,
                ]),
                state.error ? m("p.err", state.error) : null,
                state.msg ? m("p.ok", state.msg) : null,
              ]
            ),
          ])
        : m("div.card", [
            m("h2", { style: { marginTop: 0, fontSize: "1.1rem" } }, "报送读数"),
            m("p.sub", { style: { marginBottom: 0 } }, "复核员仅可查看参数与换算流水，不能提交或修改参数。"),
          ]),
      m("div.card", [
        m("h2", { style: { marginTop: 0, fontSize: "1.1rem" } }, "换算流水"),
        m("table", [
          m("thead", [
            m("tr", [
              m("th", "流水号"),
              m("th", "单据"),
              m("th", "跨段"),
              m("th", "路径"),
              m("th", "原始电压(V)"),
              m("th", "灵敏度K"),
              m("th", "额定电压(V)"),
              m("th", "微应变(με)"),
              m("th", "提交人"),
              m("th", "时间"),
            ]),
          ]),
          m(
            "tbody",
            state.logs.length
              ? state.logs.map((l) =>
                  m("tr", { key: l.id }, [
                    m("td", l.id),
                    m("td", l.reading_id),
                    m("td", l.span_code),
                    m("td", pathLabel(l.path)),
                    m("td", fmtNum(l.raw_voltage, 4)),
                    m("td", fmtNum(l.sensitivity, 3)),
                    m("td", fmtNum(l.rated_voltage, 2)),
                    m("td", fmtNum(l.microstrain, 2)),
                    m("td", l.created_by),
                    m("td", fmtTime(l.created_at)),
                  ])
                )
              : [m("tr", m("td", { colspan: 10 }, "暂无流水"))]
          ),
        ]),
      ]),
    ];
  },
};

const App = {
  oninit() {
    refreshAll();
    startPolling();
  },
  onremove() {
    if (state.timer) clearInterval(state.timer);
  },
  view() {
    if (!state.token) return m(LoginView);
    const isWriter = state.user?.role === "writer";
    return m("div.wrap", [
      topbar(isWriter),
      state.view === "convert" ? m(ConvertView) : m(ListView),
    ]);
  },
};

export default App;

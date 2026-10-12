use serde_json::{Value, json};
use std::io::{self, BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

const CATALOG: &str = include_str!("../../protocol-catalog.json");

struct Worker {
    _child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}

impl Worker {
    fn start(args: &[String]) -> io::Result<Self> {
        let python = std::env::var("DIA_MCP_PYTHON").unwrap_or_else(|_| "python3".into());
        let mut child = Command::new(python)
            .args(["-m", "dia_mcp.worker"])
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()?;
        let mut worker = Self {
            input: child.stdin.take().unwrap(),
            output: BufReader::new(child.stdout.take().unwrap()),
            _child: child,
        };
        let mut ready = String::new();
        if worker.output.read_line(&mut ready)? == 0 || ready.trim() != r#"{"ready":true}"# {
            return Err(io::Error::other(
                "Dia operations worker failed to initialize",
            ));
        }
        Ok(worker)
    }

    fn request(&mut self, value: Value) -> Result<Value, String> {
        writeln!(self.input, "{value}").map_err(|e| e.to_string())?;
        self.input.flush().map_err(|e| e.to_string())?;
        let mut line = String::new();
        if self
            .output
            .read_line(&mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err("Dia operations worker exited".into());
        }
        let response: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        if let Some(error) = response.get("error") {
            return Err(error.as_str().unwrap_or("Worker error").into());
        }
        Ok(response["value"].clone())
    }
}

fn error(id: &Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}

fn result(id: &Value, value: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":value})
}

fn handle(message: &Value, catalog: &Value, worker: &mut Worker) -> Option<Value> {
    let id = message.get("id")?;
    let method = message["method"].as_str().unwrap_or("");
    let params = &message["params"];
    let value = match method {
        "initialize" => Ok(json!({
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools":{},"resources":{},"prompts":{}},
            "serverInfo": {"name":"Dia operations","version":"0.3.0"},
            "instructions":"Dia operations. Start live work with live_get_current_context; preserve generation and prepared receipts."
        })),
        "ping" => Ok(json!({})),
        "tools/list" => Ok(json!({"tools":catalog["tools"]})),
        "resources/list" => Ok(json!({"resources":catalog["resources"]})),
        "resources/templates/list" => Ok(json!({"resourceTemplates":catalog["resourceTemplates"]})),
        "prompts/list" => Ok(json!({"prompts":catalog["prompts"]})),
        "tools/call" => {
            let name = params["name"].as_str().unwrap_or("");
            if !catalog["tools"]
                .as_array()
                .unwrap()
                .iter()
                .any(|t| t["name"] == name)
            {
                return Some(error(id, -32602, "Unknown tool"));
            }
            match worker.request(json!({"kind":"tool","name":name,"arguments":params["arguments"]}))
            {
                Ok(data) => {
                    Ok(json!({"content":[{"type":"text","text":data.to_string()}],"isError":false}))
                }
                Err(reason) => {
                    Ok(json!({"content":[{"type":"text","text":reason}],"isError":true}))
                }
            }
        }
        "resources/read" => worker
            .request(json!({"kind":"resource","uri":params["uri"]}))
            .map(|data| {
                let text = data
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| data.to_string());
                json!({"contents":[{"uri":params["uri"],"mimeType":"text/plain","text":text}]})
            }),
        "prompts/get" => worker
            .request(json!({"kind":"prompt","name":params["name"],"arguments":params["arguments"]}))
            .map(|data| json!({"messages":data})),
        _ => return Some(error(id, -32601, "Method not found")),
    };
    Some(match value {
        Ok(value) => result(id, value),
        Err(reason) => error(id, -32603, &reason),
    })
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if !args.iter().any(|a| a == "--workspace") {
        eprintln!(
            "usage: dia-mcp --workspace DIRECTORY [--dia-binary PATH] [--timeout SECONDS] [--live-socket PATH]"
        );
        std::process::exit(2);
    }
    let catalog: Value = serde_json::from_str(CATALOG)?;
    let mut worker = Worker::start(&args)?;
    for line in io::stdin().lock().lines() {
        let line = line?;
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(message) => handle(&message, &catalog, &mut worker),
            Err(_) => Some(error(&Value::Null, -32700, "Parse error")),
        };
        if let Some(response) = response {
            println!("{response}");
        }
    }
    Ok(())
}

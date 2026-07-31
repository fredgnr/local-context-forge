import childProcess from "node:child_process";
import dns from "node:dns";
import { syncBuiltinESMExports } from "node:module";
import net from "node:net";
import tls from "node:tls";

if (process.env.LCF_QMD_NATIVE_SMOKE !== "1") {
  throw new Error("QMD network trap is restricted to the native smoke gate");
}

function rejectedOperation() {
  throw new Error("QMD native smoke rejected an external process or network call");
}

const originalSocketConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function trappedSocketConnect(...arguments_) {
  const first = arguments_[0];
  const unixSocket =
    typeof first === "string" ||
    (first !== null &&
      typeof first === "object" &&
      typeof first.path === "string" &&
      first.path.startsWith("/"));
  if (!unixSocket) {
    return rejectedOperation();
  }
  return originalSocketConnect.apply(this, arguments_);
};

net.connect = (...arguments_) => {
  const socket = new net.Socket();
  return socket.connect(...arguments_);
};
net.createConnection = net.connect;
tls.connect = rejectedOperation;
dns.lookup = rejectedOperation;
dns.resolve = rejectedOperation;
dns.resolve4 = rejectedOperation;
dns.resolve6 = rejectedOperation;
dns.reverse = rejectedOperation;
childProcess.exec = rejectedOperation;
childProcess.execFile = rejectedOperation;
childProcess.fork = rejectedOperation;
childProcess.spawn = rejectedOperation;
childProcess.spawnSync = rejectedOperation;

globalThis.fetch = async () => rejectedOperation();
syncBuiltinESMExports();

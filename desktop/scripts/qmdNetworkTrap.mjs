import childProcess from "node:child_process";
import dns from "node:dns";
import dgram from "node:dgram";
import { syncBuiltinESMExports } from "node:module";
import net from "node:net";
import tls from "node:tls";

const gate =
  process.env.LCF_QMD_NATIVE_SMOKE === "1"
    ? "native-smoke"
    : process.env.LCF_QMD_SOURCE_TEST === "1"
      ? "source-test"
      : null;

if (!gate) {
  throw new Error("QMD network trap requires an explicit source-test or native-smoke gate");
}

function rejectedOperation() {
  throw new Error(`QMD ${gate} rejected an external process or network call`);
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
dgram.createSocket = rejectedOperation;
dns.lookup = rejectedOperation;
dns.resolve = rejectedOperation;
dns.resolve4 = rejectedOperation;
dns.resolve6 = rejectedOperation;
dns.reverse = rejectedOperation;
dns.promises.lookup = rejectedOperation;
dns.promises.resolve = rejectedOperation;
dns.promises.resolve4 = rejectedOperation;
dns.promises.resolve6 = rejectedOperation;
dns.promises.reverse = rejectedOperation;
childProcess.exec = rejectedOperation;
childProcess.execFile = rejectedOperation;
childProcess.fork = rejectedOperation;
childProcess.spawn = rejectedOperation;
childProcess.spawnSync = rejectedOperation;

globalThis.fetch = async () => rejectedOperation();
syncBuiltinESMExports();
process.stderr.write(`LCF_QMD_NETWORK_TRAP=active:${gate}\n`);

import { useMemo } from "react";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, Text, View } from "react-native";
import type { SessionEndEvent } from "./engine/events";
import { watchSession } from "./engine/sim";

/**
 * Placeholder screen — a smoke test, not the final animated table.
 * Runs one seeded session through the TypeScript engine and shows the
 * result. Same seed always replays the identical session.
 */
export default function App() {
  const summary = useMemo(() => {
    const events = [
      ...watchSession({
        strategy: "passline_odds",
        seed: 42,
        bankroll: 1000,
        rolls: 300,
      }),
    ];
    const end = events[events.length - 1] as SessionEndEvent;
    const rolls = events.filter((e) => e.type === "roll").length;
    const placed = events.filter((e) => e.type === "bet_placed").length;
    return {
      events: events.length,
      rolls,
      placed,
      reason: end.reason,
      finalBankroll: end.final_bankroll,
      netProfit: end.net_profit,
    };
  }, []);

  const profitStyle =
    summary.netProfit >= 0 ? styles.profit : styles.loss;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>🎲 Port Royale</Text>
      <Text style={styles.subtitle}>
        passline_odds · seed 42 · 300 rolls
      </Text>
      <View style={styles.card}>
        <Text style={styles.row}>
          Final bankroll: ${summary.finalBankroll.toFixed(2)}
        </Text>
        <Text style={[styles.row, profitStyle]}>
          Net profit: {summary.netProfit >= 0 ? "+" : ""}$
          {summary.netProfit.toFixed(2)}
        </Text>
        <Text style={styles.row}>Rolls played: {summary.rolls}</Text>
        <Text style={styles.row}>Bets placed: {summary.placed}</Text>
        <Text style={styles.row}>Session end: {summary.reason}</Text>
        <Text style={styles.row}>Events emitted: {summary.events}</Text>
      </View>
      <Text style={styles.note}>
        Engine smoke test — the animated table comes later.
      </Text>
      <StatusBar style="auto" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0e1a2b",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  title: {
    fontSize: 32,
    fontWeight: "bold",
    color: "#f5f5f5",
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 14,
    color: "#8fa3bf",
    marginBottom: 24,
  },
  card: {
    backgroundColor: "#16283f",
    borderRadius: 12,
    padding: 20,
    width: "100%",
  },
  row: {
    fontSize: 16,
    color: "#e8eef6",
    marginVertical: 4,
  },
  profit: {
    color: "#4ade80",
    fontWeight: "600",
  },
  loss: {
    color: "#f87171",
    fontWeight: "600",
  },
  note: {
    marginTop: 24,
    fontSize: 12,
    color: "#5b6b84",
    textAlign: "center",
  },
});

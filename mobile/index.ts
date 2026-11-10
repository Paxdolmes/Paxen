// App entry. The automatic-trips background task has to be defined before anything else runs, because iOS can start
// the app in the background just to report that Home or Work was left or reached (src/lib/autotrips.ts).
import './src/lib/autotrips'
import 'expo-router/entry'

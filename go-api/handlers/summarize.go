package handlers

import (
	"bytes"
	"encoding/json"
	"io/ioutil"
	"log"
	"net/http"
	"os"
)

type SummarizeRequest struct {
    Text  string `json:"text"`
    Style string `json:"style,omitempty"`
}

func Health(w http.ResponseWriter, r *http.Request) {
    w.Write([]byte("ok"))
}

func SummarizeHandler(w http.ResponseWriter, r *http.Request) {
    var req SummarizeRequest
    body, err := ioutil.ReadAll(r.Body)
    if err != nil {
        http.Error(w, "invalid body", http.StatusBadRequest)
        return
    }
    json.Unmarshal(body, &req)

    llmUrl := os.Getenv("LLM_SERVICE_URL")
    if llmUrl == "" {
        llmUrl = "http://llm-service:8000/api/summarize"
    }

    // forward original req to llm-service
    payload := map[string]string{"text": req.Text, "style": req.Style}
    pb, _ := json.Marshal(payload)
    resp, err := http.Post(llmUrl, "application/json", bytes.NewBuffer(pb))
    if err != nil {
        log.Println("error calling llm:", err)
        http.Error(w, "llm service error", http.StatusInternalServerError)
        return
    }
    defer resp.Body.Close()
    rb, _ := ioutil.ReadAll(resp.Body)
    w.Header().Set("Content-Type", "application/json")
    w.Write(rb)
}

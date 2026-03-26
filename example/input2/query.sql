SELECT class_name, AVG(score) AS avg_score
FROM exam_scores
WHERE exam_term = '2025-Fall'
GROUP BY class_name
ORDER BY avg_score DESC
LIMIT 3;
